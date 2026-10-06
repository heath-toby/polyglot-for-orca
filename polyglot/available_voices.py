"""What languages Speech Dispatcher can actually speak.

This is all that is left of the old ``voice_mapper`` module. Polyglot used
to discover every voice, read Orca's profiles, and build a voice / rate /
pitch / volume table of its own. Orca 51 does that itself: an utterance
carrying nothing but a language gets the matching voice set overlaid by
``speech_manager.apply_voice_set``, configured by the user in Orca's own
Voice Sets preferences. See the module docstring in ``speech_interceptor``.

So the only question left is which languages are worth offering to detect,
and that is answered by asking Speech Dispatcher what it has voices for.

Orca's own ``speech_manager.get_voice_families()`` would answer the same
question, but it is empty until the speech server has started, and
extensions are readied before that is guaranteed. Asking Speech Dispatcher
directly works at any point.
"""

import logging

log = logging.getLogger("polyglot")

# (voice_name, full_lang, variant, base_lang) for every voice, and the
# sorted set of base languages. Queried once -- the answer only changes
# when the user installs a synthesiser, which needs a restart anyway.
_cache = None


def _query():
    global _cache
    if _cache is not None:
        return _cache
    voices = []
    languages = set()
    try:
        import speechd
        client = speechd.SSIPClient("polyglot-voices")
        try:
            for voice_name, lang_code, variant in client.list_synthesis_voices():
                if not lang_code:
                    continue
                base = lang_code.split("-")[0].split("_")[0].lower()
                voices.append((voice_name, lang_code, variant, base))
                languages.add(base)
        finally:
            client.close()
    except Exception as error:  # pylint: disable=broad-exception-caught
        log.debug(f"Polyglot: could not list Speech Dispatcher voices: {error}")
    _cache = (voices, sorted(languages))
    return _cache


def languages():
    """Return the base language codes Speech Dispatcher has a voice for."""
    return _query()[1]


def voices_for_language(lang_code):
    """Return [(voice_name, full_lang, variant)] for one base language."""
    return [(name, full, variant)
            for name, full, variant, base in _query()[0]
            if base == lang_code]


def invalidate():
    """Forget the cached answer, so the next call re-queries."""
    global _cache
    _cache = None
