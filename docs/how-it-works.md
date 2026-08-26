# How I UwU-transformed Cyberpunk 2077's localization

Nope I did not paste onscreen to chat gee pee twee that's like committing linguistic homicide.

I extracted the compiled localization resources using WolvenKit + power of Python to make a text replacer, rebuilt them, then Boom I become cat boy Nyaaa~! No prose was rewritten only replace. The process is deterministic. Same source + same seed = same UwU transformation every time.

## What this process changes

The python script only change visible Eng text stored in localization entries `femaleVariant` and `maleVariant` fields. Menus use readable phonetic mutation, while dialogue and descriptions use lighter transformation rules so they do not become `wwwwww` soup.

## What this process doesn't touch

Audio, Texture, Localized IDs, Resource paths, CP's original archives.
