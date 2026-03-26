# Misc Decision Tree

## Step 1: File triage
Run `misc_quick_scan.py`. Build artifact index first:
- File type (magic bytes, not extension)
- Source (attached / extracted / network capture)
- Ordering / timestamp if multiple files

## Step 2: Category classification

```
Network capture (.pcap/.pcapng)? ─── tshark → follow streams → find protocol
                                      │
                                      └── encrypted? → check for key material in other files

Image file? ─── visible content relevant? → OCR pipeline first
             │
             ├── stego signals? → binwalk / zsteg (PNG) / steghide / outguess / stegsolve
             │
             └── metadata? → exiftool → GPS / author / comment / thumbnail

Archive / compressed? ─── unpack all layers → repeat triage on contents
                          └── password-protected? → check challenge text for hints / rockyou

Text / code? ─── encoding chain: base64 → hex → rot → morse → brainf*** → look up esoteric langs
               │
               └── cipher text? → frequency analysis → vigenere / substitution

Binary / executable? ─── route to Rev skill
Memory dump / filesystem? ─── Volatility / autopsy / foremost

Combination (multiple artifact types)? ─── build dependency graph:
  what artifact unlocks the next? → assembly order matters
```

## Step 3: Stego signal priority
1. LSB (zsteg for PNG, stegsolve for BMP/PNG)
2. DCT coefficients (JPEG: stegdetect, jsteg)
3. Audio: spectogram (Audacity/sox), LSB in WAV, SSTV decode
4. Video: extract frames, check metadata, audio channel

## Step 4: Encoding / cipher identification
- Random-looking base64 → try base64 decode → repeat
- Mixed case + numbers → base58 / base62
- Only hex chars → hex decode
- Dots and dashes → morse
- `><+-[].,` → brainfuck
- Whitespace-heavy → whitespace lang / zero-width steganography
- High entropy uniform → encrypted (need key from elsewhere)

## Step 5: Fragment assembly
If flag appears split across files/streams:
1. Collect all flag-like strings with provenance (file, offset, transform chain)
2. Classify: `partial fragment` vs `full candidate`
3. Order by timestamp / filename sequence / logical dependency
4. Use `flag_validate.py --dotall --merge-whitespace` to test reassembly

## Escalation order
triage → fingerprint → standard tools → stego → encoding chain → forensic deep-dive
