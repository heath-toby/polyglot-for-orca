#!/usr/bin/env bash
# Polyglot for Orca -- word list fetcher
#
# Downloads a plain word list per language into Polyglot's data directory,
# for the dictionary tier of language detection:
#
#   ~/.local/share/orca/polyglot/dictionaries/<lang>.txt
#
# The lists come from hermitdave/FrequencyWords, which derives word
# frequencies from the OpenSubtitles corpus and publishes them under
# CC-BY-SA 4.0. They are surface forms in frequency order, which is what
# detection wants: "Häuser" appears because people write it, whereas a
# spell-checker dictionary lists only the stem "Haus".
#
# Lists are cross-pruned against each other before being written -- see
# the comment on PRUNE_RATIO below for why that is not optional.
#
# Nothing here is required. With no word lists installed, detection falls
# back to script detection and Lingua exactly as before.
#
# Usage:
#   ./fetch-dictionaries.sh              # the languages Polyglot has enabled
#   ./fetch-dictionaries.sh de en ru     # these languages
#   WORDS=50000 ./fetch-dictionaries.sh  # keep more words (default 30000)

set -euo pipefail

ORCA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/orca"
DICT_DIR="$ORCA_DIR/polyglot/dictionaries"
WORDS="${WORDS:-30000}"
BASE_URL="https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018"
SOURCE_CREDIT="hermitdave/FrequencyWords (OpenSubtitles 2018), CC-BY-SA 4.0"

# A subtitle corpus is full of the other languages: "this" is the 17th most
# common word in the English list and the 5262nd in the German one, because
# German subtitles quote English. Left in, those words destroy the signal --
# detection works by finding words unique to one language, and contamination
# makes almost nothing unique. So a word is dropped from a language's list
# when another language ranks it this many times better. At 5, "this" leaves
# German and "guten" (261 de, 25916 en) leaves English, while genuinely
# shared words stay in both and simply cast no vote.
PRUNE_RATIO="${PRUNE_RATIO:-5}"

info()  { echo "  [+] $*"; }
warn()  { echo "  [!] $*"; }
error() { echo "  [ERROR] $*" >&2; exit 1; }

command -v curl >/dev/null 2>&1 || error "curl is needed to download word lists."
command -v python3 >/dev/null 2>&1 || error "python3 is needed to prune the word lists."

langs=("$@")
if [ ${#langs[@]} -eq 0 ]; then
    # Ask Polyglot's own settings which languages matter.
    mapfile -t langs < <(
        dconf read /org/gnome/orca/default/extensions/polyglot/settings 2>/dev/null \
        | grep -o "'enabled-languages': <\[[^]]*\]" \
        | grep -o "'[a-z][a-z]*'" | tr -d "'"
    )
    [ ${#langs[@]} -gt 0 ] || error "No languages given, and none found in Polyglot's settings."
    info "Using Polyglot's enabled languages: ${langs[*]}"
fi

if [ ${#langs[@]} -lt 2 ]; then
    warn "Only one language requested. Cross-pruning needs at least two, and"
    warn "the detector itself needs two lists before it will answer at all."
fi

mkdir -p "$DICT_DIR"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo ""

fetched_langs=()
for lang in "${langs[@]}"; do
    # The 50k list is the smaller, cleaner cut; fall back to the full one
    # for languages that have no 50k file.
    got=""
    for name in "${lang}_50k.txt" "${lang}_full.txt"; do
        if curl -sSfL --max-time 180 -o "$WORK/$lang.raw" "$BASE_URL/$lang/$name" 2>/dev/null; then
            got="$name"
            break
        fi
    done
    if [ -z "$got" ]; then
        warn "No word list published for '$lang' -- skipping."
        rm -f "$WORK/$lang.raw"
        continue
    fi
    echo "$BASE_URL/$lang/$got" > "$WORK/$lang.url"
    fetched_langs+=("$lang")
    info "Downloaded $lang ($got)."
done

[ ${#fetched_langs[@]} -gt 0 ] || error "Nothing was downloaded."

echo ""
WORDS="$WORDS" PRUNE_RATIO="$PRUNE_RATIO" WORK="$WORK" DICT_DIR="$DICT_DIR" \
SOURCE_CREDIT="$SOURCE_CREDIT" LANGS="${fetched_langs[*]}" python3 - <<'PYEOF'
import datetime
import os

work = os.environ["WORK"]
out_dir = os.environ["DICT_DIR"]
limit = int(os.environ["WORDS"])
ratio = float(os.environ["PRUNE_RATIO"])
credit = os.environ["SOURCE_CREDIT"]
langs = os.environ["LANGS"].split()
today = datetime.date.today().isoformat()

# lang -> {word: rank}, rank 1 being the most frequent. Ranks are what the
# pruning compares, so they are kept for every word in the raw list, not
# just the ones that survive the length filter.
ranks = {}
for lang in langs:
    table = {}
    with open(os.path.join(work, f"{lang}.raw"), encoding="utf-8", errors="replace") as handle:
        for line in handle:
            word = line.split(None, 1)[0].lower() if line.split() else ""
            if word and word not in table:
                table[word] = len(table) + 1
    ranks[lang] = table

for lang in langs:
    own = ranks[lang]
    others = [ranks[other] for other in langs if other != lang]
    kept, pruned = [], 0
    for word, rank in sorted(own.items(), key=lambda item: item[1]):
        if len(word) < 3:
            continue
        # Dominated elsewhere? Then it is not this language's word.
        if any((rank / other[word]) >= ratio for other in others if word in other):
            pruned += 1
            continue
        kept.append(word)
        if len(kept) >= limit:
            break

    with open(os.path.join(work, f"{lang}.url"), encoding="utf-8") as handle:
        url = handle.read().strip()

    path = os.path.join(out_dir, f"{lang}.txt")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(f"# Polyglot word list: {lang}\n")
        handle.write(f"# source: {credit}\n")
        handle.write(f"# file: {url}\n")
        handle.write(f"# fetched: {today}\n")
        handle.write(f"# words: {len(kept)}\n")
        handle.write(
            f"# pruned: {pruned} word(s) another language ranks at least "
            f"{ratio:g}x more highly\n"
        )
        handle.write("# order: most frequent first; one word per line; '#' starts a comment\n")
        handle.write("\n".join(kept))
        handle.write("\n")
    print(f"  [+] {lang}: {len(kept)} words kept, {pruned} pruned -> {path}")
PYEOF

echo ""
echo "Restart Orca to pick the lists up:  orca --replace &"
echo ""
