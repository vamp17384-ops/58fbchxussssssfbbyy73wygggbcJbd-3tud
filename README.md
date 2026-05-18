# Background Videos

Put your royalty-free `.mp4` background clips in this folder.

The bot picks one randomly each day and loops it to match the story length.

## Free sources (no attribution required)
- https://www.pexels.com/videos/
- https://pixabay.com/videos/

## Popular background styles for Reddit story videos
- Minecraft parkour / building
- Subway Surfers gameplay
- Satisfying cooking or food prep
- Relaxing nature (rain, ocean waves, forest)
- GTA driving / city at night
- Abstract/looping motion graphics

## File requirements
- Format: `.mp4` (H.264 preferred)
- Length: 2–10 minutes (the bot loops shorter clips automatically)
- Size: GitHub has a 100 MB per-file limit for free accounts.
  For larger files, use [Git LFS](https://git-lfs.com/) or compress first:
  ```
  ffmpeg -i input.mp4 -c:v libx264 -crf 28 -preset fast small.mp4
  ```

## Note on repo size
GitHub gives 1 GB of free storage per repo.
2–4 background clips at compressed quality fit easily within that.
If you add many clips, consider using Git LFS (also free up to 1 GB/month).
