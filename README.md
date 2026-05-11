# LK XD4000 Phase-3 Channel Diagnosis Tester

Phase-3 project for XD4000 / ATV930 Modbus TCP testing.

## New in Phase-3
- CRC @ 8441 active reference channel
- CCC @ 8442 active command channel
- CNFS @ 8020 active configuration
- LFT @ 7121 last error
- COM1 @ 64047 Modbus communication status
- Channel diagnosis button with CRC/CCC bit decode
- Command Test Checklist
- CMD@8501 raw writes remain disabled

## Build
Upload to GitHub and run: Actions -> Build XD4000 Phase3 Windows EXE -> Run workflow.

## Recommended test
1. Connect to drive.
2. Upload visible parameters.
3. Open Command Safety Test tab.
4. Click Diagnose CRC/CCC Channels.
5. Confirm if Modbus bit is active in CRC/CCC.
6. Validate LFR write/readback with safe values only.
