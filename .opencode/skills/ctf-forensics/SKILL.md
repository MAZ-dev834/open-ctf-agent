---
name: ctf-forensics
description: Digital forensics and stego workflow for PCAP, memory, disk, logs, images, audio, and layered artifacts. Use when the core blocker is extracting, correlating, or validating evidence from local artifacts. Do not use when the main blocker is public-source OSINT, exploit development, or pure cryptanalysis.
---

# Forensics CTF Workflow

## Use This Skill When
- The task centers on local artifacts: disk images, PCAPs, memory dumps, logs, media, firmware dumps, or evidence bundles.
- The main blocker is extracting the right artifact, stream, layer, or signal from local evidence.
- The solve path depends on provenance and reproducible extraction, not guesswork.

## Do Not Use This Skill When
- The answer mainly requires public web pivots or identity attribution.
- The central problem is a crypto break or program-logic recovery.
- The target is primarily a live web or pwn service.

## Session Start
1. Inventory artifact types, container layers, timestamps, and expected flag shape.
2. Choose one primary evidence lane:
   - disk/memory
   - network/PCAP
   - stego/media
   - logs/artifacts
   - signals/hardware
3. Create exactly 4 todos:
   - `inventory layers, metadata, and extraction points`
   - `choose one primary evidence lane`
   - `extract the first concrete artifact or signal`
   - `build a reproducible evidence chain to the flag`
4. Do not open parallel heavy branches before the first concrete artifact or signal appears.
5. For image/audio tasks, local transforms come before repeated OCR tuning.

## Todo Policy
- Good todo examples:
  - `reassemble suspicious HTTP object from PCAP stream 5`
  - `map nested zip and carve embedded PNG`
  - `extract browser history timestamps from memory image`
  - `compare LSB and palette anomalies on cropped region`
- Do not create vague todos such as `analyze dump` or `try stego tools`.
- Keep at most 3 active todos at once.
- If one evidence lane stalls, close it before opening the next.

## Evidence-Lane Rule
- Work one main lane at a time.
- Allowed switches:
  - file layers -> metadata timeline
  - metadata timeline -> network reconstruction
  - network reconstruction -> decoded payload analysis
  - image/audio -> diff/crop/threshold/spectrum
- If the challenge clearly becomes `ctf-osint`, `ctf-crypto`, or `ctf-misc`, keep forensics primary only if local evidence extraction is still the main blocker.

## Branch Control
- If one lane yields no new artifact, stream, or decoded signal after 3 iterations, close that todo.
- OCR is auxiliary only. It cannot be the sole main path for image-heavy tasks.
- For PCAP and memory tasks, prioritize:
  - isolate candidate objects/processes
  - reconstruct one concrete payload or execution trace
  - then decode or correlate

## Read References When
- Read `references/disk-and-memory.md` for disk, memory, VM, and coredump workflows.
- Read `references/network.md` or `references/network-advanced.md` for PCAP and timing channels.
- Read `references/steganography.md` or `references/stego-advanced.md` for image/audio stego.
- Read `references/windows.md` or `references/linux-forensics.md` for OS-specific artifacts.
- Read `references/signals-and-hardware.md` for UART, RF, side-channel, or hardware traces.

## Output
- Reproducible extraction steps and artifact paths.
- Minimal evidence chain from source artifact to decoded signal or flag.
- Final flag candidate.
