# CONTAMINATED — do not use for any verdict

July 5, 2026. The first gauntlet invocation (stamp 135106) was reported
"killed" by the Claude Code harness at ~game 82 of the SF-1700 leg, but the
bash/cutechess process tree actually survived and ran to completion (15:22:32).
A continuation run (stamp 142917) was started at 14:29:17 on that false
premise. Result: from 14:29:17 to 15:22:32 two cutechess matches ran
concurrently (concurrency=1 violated, TC 10+0.1 corrupted by CPU contention)
and appended to the same PGN files, mangling records (the MIXED sf1700 file
holds 108 Result headers / 95 parseable chunks where 118 games were played;
sf1900 holds 124 headers where 200 were played).

SALVAGED: the first 82 games of cb100_vs_sf1700_MIXED.pgn were played
strictly before 14:29:17 by a single writer — extracted to
../cb100_vs_sf1700.pgn (validated: 82/82 parse, 0 errors, W-L-D 40-32-10 =
54.9%, matches the 135106 log line at game 82). Everything else in this
folder is quarantined raw data, kept for the record.

Lesson (added to workflow): a harness "killed" status on a Windows
background bash task does NOT guarantee the child process tree died —
verify with Get-Process before restarting a gauntlet.
