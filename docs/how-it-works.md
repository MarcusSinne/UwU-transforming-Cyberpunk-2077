# How I UwU-transformed Cyberpunk 2077's localization

Nope I did not paste onscreen to chat gee pee twee that's like committing linguistic homicide.

I extracted the compiled localization resources using WolvenKit + power of Python to make a text replacer, rebuilt them, then Boom I become cat boy Nyaaa~! No prose was rewritten only replace. The process is deterministic. Same source + same seed = same UwU transformation every time.


## What this process changes

The python script only change visible Eng text stored in localization entries `femaleVariant` and `maleVariant` fields. Menus use readable phonetic mutation, while dialogue and descriptions use lighter transformation rules so they do not become `wwwwww` soup.


## What this process doesn't touch

Audio, Texture, Localized IDs, Resource paths, CP's original archives.


## 1. Get the English localization resources

The localization was packed as a loose text file. The English resources are inside RED engine `.archive` containers.

### Base game

```text
<Cyberpunk 2077>\archive\pc\content\lang_en_text.archive
```

### Phantom Liberty
```text
<Cyberpunk 2077>\archive\pc\ep1\lang_en_text.archive
```


