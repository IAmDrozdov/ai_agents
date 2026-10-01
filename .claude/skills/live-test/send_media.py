"""Put live-test media into the admin's chat with the bot, and delete test messages afterwards.

The bot posts the message (Bot API, the token from .env; it does not poll, so the droplet's bot
keeps running). A case then forwards it from Telegram Web, which is how the bot receives it.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import tempfile
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from shared.audio import SpeechSpec, synthesize
from shared.config import settings

LABEL = "🧪 live test"


def _speak(text: str, out_dir: Path) -> Path:
    """Russian speech from OpenAI TTS as Ogg/Opus — already what Telegram plays as a voice message."""
    result = synthesize(settings, text, SpeechSpec(spoken_language="Russian", output_format="opus"))
    ogg = out_dir / "voice.ogg"
    ogg.write_bytes(result.audio_bytes)
    print(f"tts: {len(text)} chars, ${result.cost.usd:.4f}")
    return ogg


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], check=True)


async def _run(args: argparse.Namespace) -> None:
    token, chat = settings.telegram_bot_token, settings.admin_telegram_id
    if token is None or chat is None:
        raise SystemExit("TELEGRAM_BOT_TOKEN and ADMIN_TELEGRAM_ID must be set in .env")
    bot = Bot(token=token.get_secret_value())
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            if args.command == "voice":
                ogg = _speak(args.say, out)
                sent = await bot.send_voice(chat, FSInputFile(ogg), caption=args.caption or None)
            elif args.command == "video-note":
                mp4 = out / "round.mp4"
                audio = _speak(args.say, out)
                _ffmpeg(
                    "-f", "lavfi", "-i", "color=c=0x2a6fdb:s=240x240:r=25", "-i", str(audio),
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(mp4),
                )  # fmt: skip
                sent = await bot.send_video_note(chat, FSInputFile(mp4), length=240)
            elif args.command == "file":
                sent = await bot.send_document(chat, FSInputFile(args.path), caption=args.caption)
            else:
                for message_id in args.ids:
                    ok = await bot.delete_message(chat, message_id)
                    print(f"deleted {message_id}: {ok}")
                return
            print(f"message_id={sent.message_id}")
    finally:
        await bot.session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_ in (("voice", "a voice message"), ("video-note", "a round video message")):
        p = sub.add_parser(name, help=f"speak TEXT with OpenAI TTS and send it as {help_}")
        p.add_argument("--say", required=True, help="what is said, in Russian")
        if name == "voice":
            p.add_argument("--caption", default="", help="caption; becomes the Annotation")
    p = sub.add_parser("file", help="send a local file as a document")
    p.add_argument("path", type=Path)
    p.add_argument("--caption", default=LABEL)
    p = sub.add_parser(
        "delete", help="delete messages in the admin chat (bot's or admin's, < 48 h)"
    )
    p.add_argument("ids", type=int, nargs="+")
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
