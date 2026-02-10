# SCOT-94.DAT Extractor

Reverse-engineering a 1994 DOS football game data file into clean,
usable datasets.

This project decodes the legacy binary file `SCOT-94.DAT` and exports
**two complete team lists with full squads** as CSV files. It's a
practical example of *digital archaeology*: taking an opaque,
undocumented format and turning it into structured data using
pattern-based parsing and a bit of curiosity.

> Built during an exploration of the classic "One Nil / Two Nil" era of
> DOS football management games.

More info: https://www.myabandonware.com/game/one-nil-soccer-manager-1ka

------------------------------------------------------------------------

## 📦 What you get

Running the script produces **two CSVs**:

### 1) `teamlist_A_21_squads.csv`

-   Based on a **64-team list** stored in 16-byte, length-prefixed
    string slots inside the file

-   Each team has **21 players**

-   Includes teams such as:

    -   Celtic
    -   Rangers
    -   Hearts
    -   Hibernians
    -   plus many European clubs

-   Columns:

        team_index, team_name, p1, p2, ... p21

### 2) `teamlist_B_16_squads.csv`

-   Based on a **second competition dataset** embedded elsewhere in the
    file

-   Uses **16-player squads**

-   Includes Scottish teams such as:

    -   Aberdeen
    -   Hibernians
    -   Hearts
    -   and others

-   Team names are extracted from a packed, Pascal-style string region

-   Columns:

        team_index, team_name, p1, p2, ... p16

------------------------------------------------------------------------

## 🧠 How it works (high level)

This is a **heuristic, reverse-engineered parser** built from observing
stable patterns in the binary file:

### Team List A

-   Discovered as a table of repeating **16-byte records**:
    `[length][text][padding]`
-   The first large table in the file is treated as the main team list

### Player name blob

-   A large region of text-like data (bytes `16300..42299` in the
    original file)
-   Contains concatenated and space-separated surnames
-   Tokenised using:
    -   character filtering
    -   CamelCase splitting (to break glued names)
    -   special handling for `Mc` / `Mac` prefixes

### Dataset A squads (21 players)

-   Extracted as **21 tokens per team**
-   Aligned to the team list using a fixed offset derived from anchor
    players (e.g. Celtic, Rangers)

### Team List B

-   Extracted from a **packed Pascal-style string region**
    (approximately bytes `1200..3000`)
-   De-duplicated and cleaned to form a second team list (includes
    Aberdeen, Hearts, Hibernians, etc.)

### Dataset B squads (16 players)

-   Extracted as **fixed-size 16-name blocks** from the same token
    stream
-   Mapped to Team List B **by order**
-   Validated using known anchors (e.g. Aberdeen: Diamond, McNaughton,
    Tiernan, Mackie, Stewart; Hibs: Fletcher, Riordan)

> This is not an official file format spec --- it's pragmatic reverse
> engineering, validated against real-world squad data.

------------------------------------------------------------------------

## 🛠 Requirements

-   Python **3.8+**
-   No external runtime dependencies (standard library only)
-   To build this README file programmatically, `pypandoc` was used, but
    the extractor script itself does **not** require it.

------------------------------------------------------------------------

## ▶️ Usage

1.  Save the extractor script as:

```{=html}
<!-- -->
```
    scot94_extract.py

2.  Place `SCOT-94.DAT` in the same directory (or provide a path).

3.  Run:

``` bash
python scot94_extract.py SCOT-94.DAT
```

4.  The script will generate:

``` text
teamlist_A_21_squads.csv
teamlist_B_16_squads.csv
```

in the current directory.

------------------------------------------------------------------------

## 📁 Example output

**teamlist_A\_21_squads.csv**

``` csv
team_index,team_name,p1,p2,...,p21
34,Celtic,Boruc,McManus,Caldwell,...
13,Rangers,Weir,Dailly,Fleck,...
...
```

**teamlist_B\_16_squads.csv**

``` csv
team_index,team_name,p1,p2,...,p16
0,Aberdeen,Esson,Anderson,Diamond,McNaughton,...
1,Hibernians,Brown,Jones,...,Fletcher,Riordan,...
...
```

------------------------------------------------------------------------

## ⚠️ Important notes

-   This script **only extracts names and squad structure** --- it does
    not decode player attributes or stats.
-   The mappings are based on **reverse-engineered patterns**, not an
    official or documented file format.
-   Changing blob offsets, tokenisation rules, or chunk sizes will
    change the output.
-   The logic is tailored specifically to the **1994-era SCOT-94.DAT**
    layout.

------------------------------------------------------------------------

## 🎯 Why this exists

This project demonstrates:

-   Reverse engineering of legacy binary formats
-   Pattern-based data extraction
-   Turning opaque historical data into modern, usable datasets
-   Practical Python for digital archaeology and data recovery

------------------------------------------------------------------------

## 📜 License / Use

Use freely for:

-   Research
-   Preservation
-   Curiosity
-   Retro game modding and analysis

If you extend this to decode player attributes or build a full formal
spec of the file format, that would be a fantastic next step.
