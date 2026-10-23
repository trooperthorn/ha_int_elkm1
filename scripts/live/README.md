# Live panel tests

Manual scripts that exercise a real M1 panel over the serial link. They are
not run by CI and are not part of the integration: each one talks to live
hardware and, in two cases, arms it.

| Script | What it does |
|---|---|
| `elk_all_areas_test.py` | Reads status for every area |
| `elk_arm_disarm_test.py` | Full arm-then-disarm cycle on **area 2** |
| `elk_valid_code_test.py` | Validates a user code against the panel |

Area 2 is used for the arm cycle deliberately: it has no zones assigned, so
arming it cannot trigger a real alarm. Point these at another area only if you
know what is wired to it.

Passcodes are read with `getpass` at run time - prompted, hidden, and never
written to disk or passed on the command line.
