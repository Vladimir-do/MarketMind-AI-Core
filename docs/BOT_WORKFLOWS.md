# Bot Workflows

## Profiles

Profile controls card writing style and validation:

- `/profile` — show active profile and available profile names.
- `/profile <name>` — switch active profile for current chat.

Profile files live in `profiles/*.yaml`.

## Single card

1. `/ozon_card`
2. Send task text.
3. Bot:
   - builds base draft,
   - searches competitors,
   - applies profile constraints,
   - returns XLSX + JSON.

## Batch cards (text message)

1. `/ozon_batch_cards`
2. Send multiline text (1 item per line, URL or freeform task).
3. Bot returns one batch XLSX + batch JSON.

## Batch cards (file)

Send `.txt` or `.csv` with:

- file caption containing `/ozon_batch_cards` (recommended), or
- plain `.txt` / `.csv` file (autodetected).

Each line is one source item.

## Safety expectations

- If marketplace blocks parsing, bot generates fallback draft from URL/title where possible.
- If competitor search is unavailable, generation continues with local draft.
- Profile `required_attributes` are enforced as placeholders (`"нужно заполнить"`).
