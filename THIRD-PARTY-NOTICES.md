# Third-party components

AI RAW Studio source is distributed under GNU GPL version 3; see LICENSE.
Third-party components retain their own licenses. This does not relicense model weights or photographs.
The complete matching application and spektrafilm source is included in the portable release's source archive.

Film modeling powered by **spektrafilm**, by **Andrea Volpato**.
https://github.com/andreavolpato/spektrafilm

- Pinned revision: `3bb2c2d2801ff68b92019cf1dbcbb133d60832bc`, version 0.3.4.
- Runtime source: GPLv3, in `third_party/spektrafilm/LICENSE`.
- Original profiles and their direct LUT derivatives: CC BY-SA 4.0, in `third_party/spektrafilm/SPEKTRAFILM_LICENSE.txt`.
- Runtime code and profiles are unmodified. Additional original upstream ICC license notices were added. See `third_party/spektrafilm/ADDITIONAL-NOTICES.txt`.
- This app uses its own UI, NEF decoder adapter, process manager and image exporter. It does not bundle the upstream Qt / napari GUI.
- Finished photographs are not relicensed by the profile license.

The portable Python film runtime includes license files and distribution metadata for its dependencies.
Python's license is `server/film-runtime/LICENSE.txt`; additional component licenses are in its `Lib/site-packages` directories.
Application dependency licenses are separately collected in `THIRD-PARTY-LICENSES` in the release.

The NVIDIA SegFormer model is separately licensed for research and evaluation.
Its original license and source notice are provided with the model and in the release as MODEL-LICENSE.txt / MODEL-SOURCE.txt.
