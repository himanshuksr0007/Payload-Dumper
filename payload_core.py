#!/usr/bin/env python3
"""
OTA Payload Extractor
Pulls partition images out of Android OTA packages. Supports all the compression types.
"""
import struct
import hashlib
import bz2
import sys
import io
import os
import brotli
import zipfile
import zstandard
from pathlib import Path


try:
    import lzma
except ImportError:
    from backports import lzma

import update_metadata_pb2 as um


# Flatten nested lists - just for fun, could've done this inline but whatever
flatten = lambda l: [item for sublist in l for item in sublist]


def u32(x):
    """Read 4-byte big-endian unsigned int"""
    return struct.unpack('>I', x)[0]


def u64(x):
    """Read 8-byte big-endian unsigned int"""
    return struct.unpack('>Q', x)[0]


def verify_contiguous(exts):
    """Check if extents form a contiguous block sequence (probably not used much)"""
    blocks = 0
    for ext in exts:
        if ext.start_block != blocks:
            return False
        blocks += ext.num_blocks
    return True


def open_payload_file(file_path):
    """Open a local payload file (plain .bin or inside a .zip).

    For ZIP files the payload.bin content is read into a BytesIO buffer so the
    returned handle stays valid after the ZipFile context closes.
    """
    if zipfile.is_zipfile(file_path):
        with zipfile.ZipFile(file_path) as zf:
            if "payload.bin" in zf.namelist():
                return io.BytesIO(zf.read("payload.bin"))
            else:
                raise ValueError("payload.bin not found in zip file")
    else:
        return open(file_path, 'rb')


def data_for_op(op, payload_file, out_file, data_offset, block_size, log_callback=None):
    """Apply a single operation - the actual extraction logic"""
    # Read the raw compressed/raw data for this operation
    payload_file.seek(data_offset + op.data_offset)
    raw_data = payload_file.read(op.data_length)

    if log_callback:
        log_callback(f"  [OP] Type: {op.type}, Data offset: {op.data_offset}, Data length: {op.data_length}")

    # Verify data integrity if hash is present
    if op.data_sha256_hash:
        calculated_hash = hashlib.sha256(raw_data).digest()
        if calculated_hash != op.data_sha256_hash:
            msg = f'Operation data hash mismatch!'
            if log_callback: 
                log_callback(msg)
            raise ValueError(msg)
        else:
            if log_callback: 
                log_callback("  [OP] SHA256 hash OK")

    try:
        # Type 0: REPLACE - just write raw data as-is
        if op.type == 0:  # REPLACE
            if log_callback: 
                log_callback(f"  [OP] REPLACE: Writing raw data: {len(raw_data)} bytes")
            out_file.seek(op.dst_extents[0].start_block * block_size)
            out_file.write(raw_data)
        
        # Type 1: REPLACE_BZ - bzip2 compressed
        elif op.type == 1:
            if log_callback: 
                log_callback(f"  [OP] REPLACE_BZ: Decompressing with BZ2: input {len(raw_data)} bytes")
            dec = bz2.BZ2Decompressor()
            data = dec.decompress(raw_data)
            if log_callback: 
                log_callback(f"  [OP] BZ2 decompressed size: {len(data)} bytes")
            out_file.seek(op.dst_extents[0].start_block * block_size)
            out_file.write(data)
        
        # Type 3 & 8: REPLACE_XZ - LZMA/XZ compressed
        elif op.type == 3 or op.type == 8:  # REPLACE_XZ
            if log_callback: 
                log_callback(f"  [OP] REPLACE_XZ: Decompressing with XZ: input {len(raw_data)} bytes")
            dec = lzma.LZMADecompressor()
            data = dec.decompress(raw_data)
            if log_callback: 
                log_callback(f"  [OP] XZ decompressed size: {len(data)} bytes")
            out_file.seek(op.dst_extents[0].start_block * block_size)
            out_file.write(data)
        
        # Type 4: REPLACE_ZSTD - Zstandard compressed
        elif op.type == 4:  # ZSTD
            if log_callback: 
                log_callback(f"  [OP] ZSTD: Decompressing with ZSTD: input {len(raw_data)} bytes")
            dec = zstandard.ZstdDecompressor().decompressobj()
            data = dec.decompress(raw_data)
            if log_callback: 
                log_callback(f"  [OP] ZSTD decompressed size: {len(data)} bytes")
            out_file.seek(op.dst_extents[0].start_block * block_size)
            out_file.write(data)
        
        # Type 2: ZERO - write a bunch of zeros
        elif op.type == 2:
            total_bytes = sum(ext.num_blocks * block_size for ext in op.dst_extents)
            if log_callback: 
                log_callback(f"  [OP] ZERO: Writing {total_bytes} bytes of zeros")
            for ext in op.dst_extents:
                out_file.seek(ext.start_block * block_size)
                out_file.write(b'\x00' * ext.num_blocks * block_size)
        
        else:
            # Unknown or unsupported operation type (including differential types 5, 6, 10)
            msg = f"[OP] Unsupported operation type: {op.type}"
            if log_callback: 
                log_callback(msg)
            raise ValueError(msg)
            
    except Exception as e:
        msg = f"Exception during operation: {str(e)} [type: {op.type}, data_offset: {op.data_offset}]"
        if log_callback: 
            log_callback(msg)
        raise


def dump_part(part, payload_file, data_offset, block_size, out_dir, log_callback=None, op_done_callback=None):
    """Extract a single partition by processing all its operations"""
    msg = f"Processing {part.partition_name} partition"
    if log_callback: 
        log_callback(msg)
    
    Path(out_dir).mkdir(exist_ok=True)

    # Open output file for this partition
    out_file = open(f'{out_dir}/{part.partition_name}.img', 'wb')

    # Process each operation for this partition
    for op in part.operations:
        data_for_op(op, payload_file, out_file, data_offset, block_size, log_callback)
        if log_callback: 
            log_callback(f"  Operation {op.type} completed.")
        # Notify caller that one more operation finished (drives per-op progress bar)
        if op_done_callback:
            op_done_callback()

    # Clean up
    out_file.close()
    
    msg = f"{part.partition_name} extraction done"
    if log_callback: 
        log_callback(msg)



def run_payload_dumper(payload_path, out_dir="output", images=None, log_callback=None,
                       progress_callback=None, cancel_flag=None, setup_callback=None):
    """Main extraction logic - reads payload header and processes partitions.
    
    setup_callback(total_partitions, total_ops): called once before the loop starts
        so the GUI can display correct totals on the progress label.
    progress_callback(percent 0-100): called after every individual operation
        for smooth, granular progress bar updates.
    """
    if log_callback: 
        log_callback("Opening payload file...")
    
    with open_payload_file(payload_path) as payload_file:
        # Verify magic header
        magic = payload_file.read(4)
        if magic != b'CrAU':
            msg = "Invalid magic header, not an OTA payload"
            if log_callback: 
                log_callback(msg)
            raise ValueError(msg)
        
        # Check format version
        file_format_version = u64(payload_file.read(8))
        if file_format_version != 2:
            msg = f"Unsupported file format version: {file_format_version}"
            if log_callback: 
                log_callback(msg)
            raise ValueError(msg)
        
        # Read manifest
        manifest_size = u64(payload_file.read(8))
        metadata_signature_size = 0
        if file_format_version > 1:
            metadata_signature_size = u32(payload_file.read(4))
        
        manifest = payload_file.read(manifest_size)
        metadata_signature = payload_file.read(metadata_signature_size)
        
        # Everything after the manifest/metadata is partition data
        data_offset = payload_file.tell()
        
        # Parse the manifest
        dam = um.DeltaArchiveManifest()
        dam.ParseFromString(manifest)
        block_size = dam.block_size

        # Figure out which partitions to extract
        parts_to_dump = dam.partitions if not images else [
            part for part in dam.partitions if part.partition_name in (images if images else [])
        ]
        
        total_parts = len(parts_to_dump)
        # Count total operations across all partitions for smooth per-op progress
        total_ops = sum(len(p.operations) for p in parts_to_dump)
        
        # Fire setup callback so the GUI knows the denominators before anything starts
        if setup_callback:
            setup_callback(total_parts, total_ops)
        
        # Mutable counter for completed operations (list so closure can mutate it)
        ops_done = [0]
        
        def on_op_done():
            """Called after each operation completes; emits smooth granular progress."""
            ops_done[0] += 1
            if progress_callback and total_ops > 0:
                progress_callback(int(ops_done[0] / total_ops * 100))
        
        for idx, part in enumerate(parts_to_dump):
            # Check if extraction was cancelled
            if cancel_flag and cancel_flag():
                if log_callback: 
                    log_callback("Extraction cancelled.")
                break
            
            dump_part(
                part, payload_file, data_offset, block_size, out_dir,
                log_callback, on_op_done
            )
    
    if log_callback: 
        log_callback("All done.")