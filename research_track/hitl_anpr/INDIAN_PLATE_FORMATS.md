# Indian registration plate formats

What the validator (`src/anpr_hitl/indian_plates.py`) accepts, the exceptions it knows, and where each rule comes from.
Compiled 2026-10-16 from the sources in section 7. Text is compared after normalising to A-Z and 0-9 (spaces, hyphens,
the broad arrow and non-Latin script are dropped). A read is **never rewritten**; invalid reads get a reason code.

## 1. The standard plate (since 1 July 1989)

```
  MH   12   AB   1234
  |    |    |    '-- number : 4 digits, 0001-9999 (leading zeros kept)
  |    |    '------- series : 1-3 letters, never I or O
  |    '------------ zone   : RTO number, 2 digits (01-99)
  '----------------- state  : 2-letter state / UT code
```

| part | rule | reason code if broken |
|---|---|---|
| state | one of the 36 current or 4 retired codes (section 2) | `unknown_state` |
| zone (RTO) | exactly 2 digits, not `00` (Delhi: see section 3) | `rto_not_two_digits`, `rto_zero` |
| series | 1-3 letters from A-Z without I and O | `no_series_letters`, `series_contains_I_or_O` |
| number | exactly 4 digits, not `0000` | `pattern_mismatch`, `number_zero` |

## 2. State and UT codes

Current (36): AN AP AR AS BR CG CH DD DL GA GJ HP HR JH JK KA KL LA LD MH ML MN MP MZ NL OD PB PY RJ SK TG TN TR UK UP WB.
`DD` is the merged UT of Dadra and Nagar Haveli and Daman and Diu.

Retired (still valid on vehicles registered while they were current; the validator accepts them and adds a note):

| code | was | last issued | now |
|---|---|---|---|
| UA | Uttaranchal | 2007-10-31 | UK |
| OR | Orissa | 2012-08-30 | OD |
| DN | Dadra and Nagar Haveli | 2020-01-25 | DD |
| TS | Telangana | 2024-03-14 | TG |

## 3. Exceptions inside the standard format

| exception | rule in the validator |
|---|---|
| **Delhi (DL)** | RTO number has **no leading zero**: `DL 1`, `DL 3`, ... A 2-digit number (`DL 10`, `DL 01`) is also accepted. The **first series letter is the vehicle category** (C car, S two-wheeler, T city taxi, P bus, R autorickshaw ...); an unlisted category letter is only a note. `DL 3C AB 1234` reads as state DL, zone 3, series CAB, number 1234. |
| **Karnataka (KA)** | Some series have **no letters** (`KA 01 1234`). Accepted for KA only; anywhere else a missing series is rejected (`no_series_letters`) because a read that lost its letters looks exactly like that. |
| **Andhra Pradesh (AP)** | One common zone number for the whole state (AP 39, AP 40 since 2023). Fits the standard pattern, no special rule. |
| reserved zones / letters | Many states reserve zone numbers (ML 01 government, CG 01 governor, KL 15 KSRTC ...) or series letters (TN `G` government, AP/TS `Z` state buses, Gujarat `Y` GSRTC ...). These still fit the pattern, so they are valid; the validator does not interpret them. |

## 4. Special formats

| kind | pattern | example | notes |
|---|---|---|---|
| Bharat series `bh` | `YY BH #### XX` | `22 BH 1234 AB` | YY = year of registration, 21 or later and not in the future; #### = 0000-9999; XX = **1-2 letters, no I or O** |
| Vintage `vintage` | `SS VA XX ####` | `MH VA AB 0123` | XX = 2 letters, no I or O |
| Armed forces `military` | `^ YY C ###### L` | `01Z012345A` | the broad arrow is dropped by normalisation; YY = year procured; C = class letter; 6-digit serial; check letter. Class letters are only noted (sources disagree). |
| Diplomatic `diplomatic` | `NNN TT NNNN` | `12 CD 3456`, `11 CD 1A` | mission number 1-3 digits (no leading zero); TT = CD embassy, CC consulate, UN United Nations, IOD international organisation; number 1-4 digits, no leading zero, optional letter suffix (`1A` = head of mission's second car) |
| Temporary `temporary` | `T MMYY SS #### L` | `T1123LA0123A` | month 01-12, year 21 or later, valid state, 1-2 letters without I and O (31 Mar 2021 notification) |
| Trade `trade` | `SS RR C #### TC N` | `LA01C0001TC0001` | C = category A-J; holder number 4 digits; vehicle number 1-4 digits (14 Sep 2022 notification) |
| Trade, old `trade_legacy` | `SS RR TC ######` | `UP16TC020007` | pre-2022 format, still valid until it expires |

## 5. Recognised but not validated

* **1940-1989 three-letter plates** (`MRC 1234`): the district-letter tables are not available, so these are rejected with
  `legacy_1940_1989_not_validated` so you can spot them in the detailed CSV. Pre-1940 plates, princely-state plates
  (`MYSORE 1`) and the colonial Pondicherry/Goa formats are not handled.
* Vehicles of the President, Governors and the MEA protocol division carry the national emblem instead of a number.

## 6. What is enforced and what is only information

Enforced (a read failing any of these is not valid and shows as `nil` in `plates.csv`): the patterns above, state code,
`00` zone, `0000` number, I/O in series letters, BH/temporary year range, temporary month.

Information only (never rejects): Delhi category, retired-state note, blank series (KA), military class, diplomatic type.

**The zone is checked for shape only, not against a list of real RTO offices.** The public list (Wikipedia's "List of
Regional Transport Office districts in India", 1,192 codes parsed on 2026-10-16) is too incomplete to enforce: the
Maharashtra, Manipur, Gujarat and Andaman sections did not parse and states have large gaps (AP 6-15, BR 12-18,
UP 2-9). A whitelist built from it would reject real plates. An official list (Parivahan / state transport departments)
would let `classify_plate` check zones too.

## 7. Sources and where they disagree

* Wikipedia, *Vehicle registration plates of India* (raw wikitext fetched 2026-10-16): standard format, state codes,
  Delhi, Karnataka and other state notes, VA, BH, armed forces, diplomatic, temporary (MoRTH 31 Mar 2021), trade
  (MoRTH 14 Sep 2022), historical formats.
  <https://en.wikipedia.org/wiki/Vehicle_registration_plates_of_India>
* Wikipedia, *List of Regional Transport Office districts in India*: zone numbers per state (incomplete, see above).
  <https://en.wikipedia.org/wiki/List_of_Regional_Transport_Office_districts_in_India>
* PIB, Ministry of Road Transport and Highways, BH series (GSR 594(E), 26 Aug 2021, effective 15 Sep 2021):
  `YY BH #### XX`, YY = year of first registration, #### = 0000-9999, XX = alphabets AA to ZZ.
  <https://www.pib.gov.in/PressReleasePage.aspx?PRID=1749764&reg=48&lang=2> (quoted via a search result; the page
  itself returned HTTP 403 to a direct fetch).
* PIB, new mark `DD` for the merged UT of Dadra and Nagar Haveli and Daman and Diu.
  <https://www.pib.gov.in/newsite/PrintRelease.aspx?relid=197595&reg=48&lang=2>

Open points (decisions made, and why):

1. **I and O in series letters.** Wikipedia and several commercial sites say they are never used (to avoid confusion
   with 1 and 0). No rule text saying so was found, and the PIB text for BH only says "AA to ZZ". The validator excludes
   them (`EXCLUDED_SERIES_LETTERS`): wrongly rejecting a real plate costs a manual entry, wrongly accepting an O/0 or
   I/1 confusion would put a wrong plate into the data.
2. **Military class letters** differ between sources (Wikipedia lists A-H, J, K, P, Q, R, X; others add D and use other
   meanings). Any letter is accepted; the known ones are noted.
3. **BH letters:** one or two letters (Wikipedia) versus exactly AA to ZZ (PIB). One or two are accepted.
4. **Diplomatic mission numbers** (1-160 in the Wikipedia list, with most country names missing) are not checked.

Change a rule by editing the constants at the top of `indian_plates.py` (`EXCLUDED_SERIES_LETTERS`,
`BLANK_SERIES_STATES`, `BH_FIRST_YEAR`, ...) and the matching case in `tests/test_indian_plates.py`.
