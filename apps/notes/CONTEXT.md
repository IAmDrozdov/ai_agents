# Notes — glossary

A single owner's "save for later" store: things captured from a phone through the maxi-bot
Telegram bot, filed into Sections automatically, looked through and corrected in the admin Mini App.
Kept apart from the repo-level `CONTEXT.md` because some words mean something else there
(**Source** most of all). Here, the **Owner** is the maxi-bot admin.

## Language

**Owner**:
The one person the bot answers and the Mini App serves.
_Avoid_: user, admin, account

**Item**:
One saved thing — a Link, a Note, a File or a Voice.
_Avoid_: entry, record, post, bookmark, запись

**Link**:
An Item whose content is the one URL in its Capture, optionally with the Owner's Annotation.
_Avoid_: bookmark, url item

**Note**:
An Item that is text with no URL, or with more than one; the text is kept whole.
_Avoid_: memo, message, text item

**File**:
An Item that is a photo, video or non-text document sent to the bot; Telegram keeps the bytes, notes keep the `file_id` and a preview image.
_Avoid_: attachment, upload

**Voice**:
An Item that is speech sent to the bot — a voice message or a round video message; Telegram keeps the bytes, notes keep the `file_id` and its Transcript.
_Avoid_: audio, recording, голосовуха

**Reminder**:
Any Item, of any kind, that has a Due; removing the Due makes it a plain Item again. Not a fifth kind.
_Avoid_: alarm, notification, task, напоминалка

**Due**:
The moment a Reminder is for; the bot sends the Reminder back to the Owner then, and the Owner can move it later.
_Avoid_: deadline, remind time, trigger, срок

**Overdue**:
A Reminder whose Due has passed while its Status is still todo; read off the clock, never set, and not a Status value. A done Item is never Overdue.
_Avoid_: late, expired, missed

**Transcript**:
The text of what is said in a Voice, written by Enrichment and never edited by the Owner.
_Avoid_: text, caption, расшифровка

**Sender**:
Who a forwarded Capture came from — a person, a chat or a channel. Never the Author.
_Avoid_: author, from, forwarder

**Annotation**:
The Owner's own words sent alongside a Link.
_Avoid_: note, comment, caption

**Capture**:
Sending the bot a message that becomes exactly one Item.
_Avoid_: save, ingest, submit, forward

**Acknowledgement**:
The bot's single reaction on the Owner's Capture message, saying whether to wait, nothing to do, or take a look; the bot leaves no message of its own, except one line naming the Due when the Capture became a Reminder.
_Avoid_: confirmation, receipt, card, reply, ack (in prose)

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
The swappable LLM-backed component that produces an Item's Filing and Gist, and its Due when the Item's text asks to be reminded.
_Avoid_: AI, model, LLM (in domain talk)

**Enrichment**:
What is fetched and derived for an Item after Capture: title, Source, Author, caption, thumbnail, a Voice's Transcript, Gist.
_Avoid_: scraping, processing, decoding, metadata

**Thumbnail**:
The small square picture a card shows, cut during Enrichment from a Link's cover or a File's preview and kept with the Item; never loaded from the Link's site.
_Avoid_: cover, preview, image, обложка

**Gist**:
The one-or-two-sentence Russian summary of an Item written by the Classifier.
_Avoid_: summary, description, суть, TL;DR

**Author**:
The person or channel who made a Link's content; not who sent it (that is the Sender).
_Avoid_: creator, owner, sender

**Source**:
The platform or site a Link came from (YouTube, Instagram, TikTok, a domain).
_Avoid_: provider, origin, site

**Status**:
Whether the Owner has taken an Item up yet: todo, or done once they have — a series they started watching is done. There is no in-progress value.
_Avoid_: state, stage, progress, viewed, started, archived, open, closed

**Dashboard**:
The Mini App's first tab, infographics only: how many Items are todo and how many of them are Overdue, how many were Captured and done each day, and how the todo Items spread over Sections; tapping a Section there, or the Overdue count, opens it in the Items tab.
_Avoid_: overview, home, stats, обзор

**Search**:
Finding Items in the Mini App by the words in their text fields, across every Section and both Statuses.
_Avoid_: filter, find, lookup

**Browse**:
Reading Sections and Items from inside the bot.
_Avoid_: view, list, search
