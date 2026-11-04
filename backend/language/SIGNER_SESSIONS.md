# Signer recording sessions

The sign library is the ground truth for both directions: recognition matches against
it, and the avatar replays it. Its quality caps everything else, so sessions are run
with care. Cluster B's recorder captures the takes; `language.sessions` runs the session.

## Before

1. **Consent, in sign.** Run `python -m language.sessions consent --signer S01` with an
   interpreter present if you are not fluent. Each scope (demo, dataset, raw video, public
   release) is separate and optional. The signer can withdraw at any time. Use
   pseudonymous IDs (S01, S02); real names live only in the consent file, which stays
   out of git.
2. **Review the vocabulary together.** Confirm each English meaning matches the sign
   they will make, note regional variants, and correct `grammar_notes`.
3. **Setup.** The signer wears the glasses (the library must be in the glasses' view).
   Plain background, even light, no backlight, sleeves that contrast with skin. Note the
   dominant hand; normalisation mirrors left-handers.
4. **Plan.** `python -m language.sessions plan --signer S01 --tier 1 --takes 5`

| Plan | Shots | Time at ~12 s per take |
|---|---|---|
| Tier 1 (first 10 signs), 5 takes | 50 | ~10 min |
| Demo set (tier ≤ 2, 38 signs), 5 takes | 190 | ~40 min + breaks |

## During

`python -m language.sessions run data/sessions/<date>_S01 --on-take "<recorder command>"`

- **Round robin.** Every sign once, then every sign again in a new order. This captures
  natural variation instead of five copies of one movement, and spreads fatigue evenly.
  Round 1 starts with the emergency signs so even a short session covers them.
- **Each take** starts and ends with the hands down at rest. This matches the segmentation
  rule (a sign starts when the hands rise into frame and ends when they drop). Natural
  speed, not exaggerated. Hands in frame at the peak of the sign.
- **Mark honestly.** Enter = good, `b` = bad with a reason, `r` = redo, `s` = skip a sign
  the signer isn't sure of. Progress saves after every take; `q` and resume any time.
- **Breaks** every ~40 takes (the tool reminds you). Water, and ask how they are doing.

## After

- `python -m language.sessions status` shows good takes per sign, flags signs where the
  recorder's file count differs from the log, and reports milestone 1 readiness
  (≥ 3 good takes per tier-1 sign).
- Back up `data/` the same day. Delete raw video unless the signer consented to keep it.
- A second signer, even for tier 1 only, improves generalisation more than extra takes
  from the first.
