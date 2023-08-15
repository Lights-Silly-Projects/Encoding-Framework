# Light's Encoding Framework

"My" encoding framework.
This is what I use when running encodes.

This can in many ways be considered vs-encode v2.0.
It now uses (vs)muxtools to perform most tasks in the back,
and includes a bunch of my own additions for my own encodes.

You're free to use this,
but make sure you change it up to suit your needs!

## How to use

This script consists of three main components:

-   The ScriptInfo class
-   The Encode class
-   The Preview class

For a list of properties and methods these objects expose,
please consult the class directly in your code editor.

### ScriptInfo

This contains a lot of core information from the script being run.
This should always be called at the start of the script,
and you should pass `__file__` to it when initializing the class.

### Encode

Pertains to running the encodes,
including trimming of relevant files,
finding chapters, etc.

When initializing the class,
you must pass the ScriptInfo object and the filtered VideoNode.
You can then call other methods to handle the chapters, audio, etc.
Make sure you call `mux` at the end!

## Preview

The simplest of the classes,
this is simply a helper class used for setting output nodes.
Calling `set_output_nodes` is usually all you will do with this class.

When initializing the class,
you must pass the ScriptInfo object.

## Features

Currently this package provides the following on top of (vs)muxtools:

-   A handful of functions I use from time to time that don't have a place in any current packages as-is. They are considered experimental
-   Add timecode files to the video mux if found
-   Additional kernels used for de- and downscaling
-   Audio track reordering and removal
-   Auto-updating function that automatically pulls from this repository
-   Better support for external audio tracks (doesn't auto-delete them anymore unlike muxtools)
-   Create a log file with information from this package
-   Create or append to a .gitignore file if necessary
-   DGIndex(NV) demuxing and indexing
-   Disables chapter generation if it's not an episode (chapters can be forced)
-   Doesn't trim or encode audio files if files already exist
-   Find audio files from DGIndex(NV) demuxing
-   Keyframe generation (+ lock file). Automatically regenerates if it doesn't match the current clip
-   Lossless intermediary video files when encoding
-   Set output nodes for every clip and audio track when previewing the filterchain
-   Support for prefiltered clips (such as IVTC'd or spliced clips), albeit fairly limited
-   Trim and encode multiple audio tracks at once

## Planned features

These features are currently planned and will likely be implemented at a future date.

-   Add information from subprocesses to the log file
-   Check for duplicate audio tracks and automatically dedupe
-   Determine video settings based on input clip (currently falls back to vsmuxtools defaults)
-   Greatly improve the prefiltering logic. Currently it's highly cursed
-   Make it so the user is no longer required to pass `__file__` to ScriptInfo. Should be easy, I'm just lazy
-   Turn `Preview.set_output_nodes` into a classmethod?
-   Upload and download from an FTP defined in the config file
