# Notes — glossary

A single owner's "save for later" store: things captured from a phone through the ai_agents
Telegram bot, filed into sections automatically, sorted and tidied in the admin Mini App.
Kept apart from the repo-level `CONTEXT.md` because some words mean something else there
(**Source** most of all). Here, the **Owner** is the ai_agents admin.

## Language

**Owner**:
The one person the bot answers and the Mini App serves.
_Avoid_: user, admin, account

**Item**:
One saved thing — a Link, a Note or a File.
_Avoid_: entry, record, post, bookmark, запись

**Link**:
An Item whose content is a URL, optionally with the Owner's Annotation.
_Avoid_: bookmark, url item

**Note**:
An Item that is plain text with no URL.
_Avoid_: memo, message, text item

**File**:
An Item that is a photo, video or non-text document sent to the bot; Telegram keeps the bytes, notes keep the `file_id` and a preview image.
_Avoid_: attachment, upload

**Annotation**:
The Owner's own words sent alongside a Link.
_Avoid_: note, comment, caption

**Capture**:
Sending the bot a message that becomes one or more Items.
_Avoid_: save, ingest, submit, forward

**Acknowledgement**:
The bot's reply to a Capture, edited in place when Enrichment lands; carries the Filing keyboard.
_Avoid_: confirmation, receipt, card, ack (in prose)

**Section**:
A category the Owner files Items under; an Item is in one or more.
_Avoid_: tag, folder, category, label, list, cluster

**Other**:
The built-in Section that cannot be deleted and holds every Item that would otherwise have no Section.
_Avoid_: misc, uncategorised, inbox, unsorted

**Filing**:
The set of Sections an Item is in; assigned by the Classifier at Capture, changed by the Owner afterwards.
_Avoid_: tagging, categorisation, classification result, pre-clustering

**Classifier**:
The swappable LLM-backed component that produces an Item's Filing and Gist.
_Avoid_: AI, model, LLM (in domain talk)

**Enrichment**:
What is fetched and derived for a Link: title, Source, author, caption, thumbnail, Gist.
_Avoid_: scraping, processing, decoding, metadata

**Gist**:
The one-or-two-sentence Russian summary of an Item written by the Classifier.
_Avoid_: summary, description, суть, TL;DR

**Source**:
The platform or site a Link came from (YouTube, Instagram, TikTok, a domain).
_Avoid_: provider, origin, site

**Status**:
An Item's progress: new, started, done.
_Avoid_: state, stage, progress, viewed

**Placement**:
Where an Item lives: active, archived, trashed. Independent of Status.
_Avoid_: state, lifecycle, visibility, folder

**Archive**:
The Placement for Items kept out of sight; never purged.
_Avoid_: done, hidden

**Trash**:
The Placement for Items awaiting deletion; purged after 30 days.
_Avoid_: bin, deleted, removed

**Reviewed**:
Whether the Owner has looked at an Item's Filing since Capture.
_Avoid_: confirmed, checked, triaged

**Sorting pass**:
The Owner's periodic session in the Mini App working through unreviewed Items.
_Avoid_: triage, inbox zero, review queue

**Browse**:
Reading Sections and Items from inside the bot.
_Avoid_: view, list, search
