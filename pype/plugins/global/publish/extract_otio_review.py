"""
Requires:
    instance -> handleStart
    instance -> handleEnd
    instance -> otioClip
    instance -> otioReviewClips

Optional:
    instance -> workfileFrameStart
    instance -> resolutionWidth
    instance -> resolutionHeight

Provides:
    instance -> otioReviewClips
"""

import os
import clique
import opentimelineio as otio
from pyblish import api
import pype


class ExtractOTIOReview(pype.api.Extractor):
    """
    Extract OTIO timeline into one concuted image sequence file.

    The `otioReviewClip` is holding trimmed range of clips relative to
    the `otioClip`. Handles are added during looping by available list
    of Gap and clips in the track. Handle start (head) is added before
    first Gap or Clip and Handle end (tail) is added at the end of last
    Clip or Gap. In case there is missing source material after the
    handles addition Gap will be added. At the end all Gaps are converted
    to black frames and available material is converted to image sequence
    frames. At the end representation is created and added to the instance.

    At the moment only image sequence output is supported

    """

    # order = api.ExtractorOrder
    order = api.CollectorOrder
    label = "Extract OTIO review"
    hosts = ["resolve"]
    families = ["review"]

    # plugin default attributes
    temp_file_head = "tempFile."
    to_width = 800
    to_height = 600
    output_ext = ".jpg"

    def process(self, instance):
        # TODO: convert resulting image sequence to mp4
        # TODO: add oudio ouput to the mp4 if audio in review is on.

        # get otio clip and other time info from instance clip
        handle_start = instance.data["handleStart"]
        handle_end = instance.data["handleEnd"]
        otio_review_clips = instance.data["otioReviewClips"]

        # add plugin wide attributes
        self.representation_files = list()
        self.used_frames = list()
        self.workfile_start = int(instance.data.get(
            "workfileFrameStart", 1001))
        self.padding = len(str(self.workfile_start))
        self.used_frames.append(self.workfile_start)
        self.to_width = instance.data.get(
            "resolutionWidth") or self.to_width
        self.to_height = instance.data.get(
            "resolutionHeight") or self.to_height

        # skip instance if no reviewable data available
        if (not isinstance(otio_review_clips[0], otio.schema.Clip)) \
                and (len(otio_review_clips) == 1):
            self.log.warning(
                "Instance `{}` has nothing to process".format(instance))
            return
        else:
            self.staging_dir = self.staging_dir(instance)
            if not instance.data.get("representations"):
                instance.data["representations"] = list()

        # loop available clips in otio track
        for index, r_otio_cl in enumerate(otio_review_clips):
            # get frame range values
            src_range = r_otio_cl.source_range
            start = src_range.start_time.value
            duration = src_range.duration.value
            available_range = None
            self.actual_fps = src_range.duration.rate

            # add available range only if not gap
            if isinstance(r_otio_cl, otio.schema.Clip):
                available_range = r_otio_cl.available_range()
                self.actual_fps = available_range.duration.rate

            # reframing handles conditions
            if (len(otio_review_clips) > 1) and (index == 0):
                # more clips | first clip reframing with handle
                start -= handle_start
                duration += handle_start
            elif len(otio_review_clips) > 1 \
                    and (index == len(otio_review_clips) - 1):
                # more clips | last clip reframing with handle
                duration += handle_end
            elif len(otio_review_clips) == 1:
                # one clip | add both handles
                start -= handle_start
                duration += (handle_start + handle_end)

            if available_range:
                available_range = self._trim_available_range(
                    available_range, start, duration, self.actual_fps)

            # media source info
            if isinstance(r_otio_cl, otio.schema.Clip):
                path = r_otio_cl.media_reference.target_url
                metadata = r_otio_cl.media_reference.metadata

                if metadata.get("padding"):
                    # render image sequence to sequence
                    dir_path, collection = self._make_sequence_collection(
                        path, available_range, metadata)

                    # render segment
                    self._render_seqment(
                        sequence=[dir_path, collection])
                    # generate used frames
                    self._generate_used_frames(
                        len(collection.indexes))
                else:
                    # render video file to sequence
                    self._render_seqment(
                        video=[path, available_range])
                    # generate used frames
                    self._generate_used_frames(
                        available_range.duration.value)

            else:
                self._render_seqment(gap=duration)
                # generate used frames
                self._generate_used_frames(duration)

        # creating and registering representation
        representation = self._create_representation(start, duration)
        instance.data["representations"].append(representation)
        self.log.info(f"Adding representation: {representation}")

    def _create_representation(self, start, duration):
        """
        Creating representation data.

        Args:
            start (int): start frame
            duration (int): duration frames

        Returns:
            dict: representation data
        """

        end = start + duration

        # create default representation data
        representation_data = {
            "frameStart": start,
            "frameEnd": end,
            "stagingDir": self.staging_dir,
            "tags": ["review", "ftrackreview", "delete"]
        }

        collection = clique.Collection(
            self.temp_file_head,
            tail=self.output_ext,
            padding=self.padding,
            indexes=set(self.used_frames)
        )
        start = min(collection.indexes)
        end = max(collection.indexes)

        files = [f for f in collection]
        ext = collection.format("{tail}")
        representation_data.update({
            "name": ext[1:],
            "ext": ext[1:],
            "files": files,
            "frameStart": start,
            "frameEnd": end,
        })
        return representation_data

    def _trim_available_range(self, avl_range, start, duration, fps):
        """
        Trim available media range to source range.

        If missing media range is detected it will convert it into
        black frames gaps.

        Args:
            avl_range (otio.time.TimeRange): media available time range
            start (int): start frame
            duration (int): duration frames
            fps (float): frame rate

        Returns:
            otio.time.TimeRange: trimmed available range
        """
        avl_start = int(avl_range.start_time.value)
        src_start = int(avl_start + start)
        avl_durtation = int(avl_range.duration.value - start)

        # if media start is les then clip requires
        if src_start < avl_start:
            # calculate gap
            gap_duration = src_start - avl_start

            # create gap data to disk
            self._render_seqment(gap=gap_duration)
            # generate used frames
            self._generate_used_frames(gap_duration)

            # fix start and end to correct values
            start = 0
            duration -= len(gap_duration)

        # if media duration is shorter then clip requirement
        if duration > avl_durtation:
            # calculate gap
            gap_start = int(src_start + avl_durtation)
            gap_end = int(src_start + duration)
            gap_duration = gap_end - gap_start

            # create gap data to disk
            self._render_seqment(gap=gap_duration, end_offset=avl_durtation)
            # generate used frames
            self._generate_used_frames(gap_duration, end_offset=avl_durtation)

            # fix duration lenght
            duration = avl_durtation

        # return correct trimmed range
        return self._trim_media_range(
            avl_range, self._range_from_frames(start, duration, fps)
        )

    def _render_seqment(self, sequence=None,
                        video=None, gap=None, end_offset=None):
        """
        Render seqment into image sequence frames.

        Using ffmpeg to convert compatible video and image source
        to defined image sequence format.

        Args:
            sequence (list): input dir path string, collection object in list
            video (list)[optional]: video_path string, otio_range in list
            gap (int)[optional]: gap duration
            end_offset (int)[optional]: offset gap frame start in frames

        Returns:
            otio.time.TimeRange: trimmed available range
        """
        # get rendering app path
        ffmpeg_path = pype.lib.get_ffmpeg_tool_path("ffmpeg")

        # create path  and frame start to destination
        output_path, out_frame_start = self._get_ffmpeg_output()

        if end_offset:
            out_frame_start += end_offset

        # start command list
        command = [ffmpeg_path]

        if sequence:
            input_dir, collection = sequence
            in_frame_start = min(collection.indexes)

            # converting image sequence to image sequence
            input_file = collection.format("{head}{padding}{tail}")
            input_path = os.path.join(input_dir, input_file)

            # form command for rendering gap files
            command.extend([
                "-start_number {}".format(in_frame_start),
                "-i {}".format(input_path)
            ])

        elif video:
            video_path, otio_range = video
            frame_start = otio_range.start_time.value
            input_fps = otio_range.start_time.rate
            frame_duration = otio_range.duration.value
            sec_start = self._frames_to_secons(frame_start, input_fps)
            sec_duration = self._frames_to_secons(frame_duration, input_fps)

            # form command for rendering gap files
            command.extend([
                "-ss {}".format(sec_start),
                "-t {}".format(sec_duration),
                "-i {}".format(video_path)
            ])

        elif gap:
            sec_duration = self._frames_to_secons(
                gap, self.actual_fps)

            # form command for rendering gap files
            command.extend([
                "-t {} -r {}".format(sec_duration, self.actual_fps),
                "-f lavfi",
                "-i color=c=black:s={}x{}".format(self.to_width,
                                                  self.to_height),
                "-tune stillimage"
            ])

        # add output attributes
        command.extend([
            "-start_number {}".format(out_frame_start),
            output_path
        ])
        # execute
        self.log.debug("Executing: {}".format(" ".join(command)))
        output = pype.api.subprocess(" ".join(command), shell=True)
        self.log.debug("Output: {}".format(output))

    def _generate_used_frames(self, duration, end_offset=None):
        """
        Generating used frames into plugin argument `used_frames`.

        The argument `used_frames` is used for checking next available
        frame to start with during rendering sequence segments.

        Args:
            duration (int): duration of frames needed to be generated
            end_offset (int)[optional]: in case frames need to be offseted

        """

        padding = "{{:0{}d}}".format(self.padding)
        if end_offset:
            new_frames = list()
            start_frame = self.used_frames[-1]
            for index in range((end_offset + 1),
                               (int(end_offset + duration) + 1)):
                seq_number = padding.format(start_frame + index)
                self.log.debug(
                    f"index: `{index}` | seq_number: `{seq_number}`")
                new_frames.append(int(seq_number))
            new_frames += self.used_frames
            self.used_frames = new_frames
        else:
            for _i in range(1, (int(duration) + 1)):
                if self.used_frames[-1] == self.workfile_start:
                    seq_number = padding.format(self.used_frames[-1])
                    self.workfile_start -= 1
                else:
                    seq_number = padding.format(self.used_frames[-1] + 1)
                    self.used_frames.append(int(seq_number))

    def _get_ffmpeg_output(self):
        """
        Returning ffmpeg output command arguments.

        Returns:
            str: output_path is path for image sequence output
            int: out_frame_start is starting sequence frame

        """
        output_file = "{}{}{}".format(
            self.temp_file_head,
            "%0{}d".format(self.padding),
            self.output_ext
        )
        # create path to destination
        output_path = os.path.join(self.staging_dir, output_file)

        # generate frame start
        out_frame_start = self.used_frames[-1] + 1
        if self.used_frames[-1] == self.workfile_start:
            out_frame_start = self.used_frames[-1]

        return output_path, out_frame_start

    @staticmethod
    def _frames_to_secons(frames, framerate):
        """
        Returning secons.

        Args:
            frames (int): frame
            framerate (flaot): frame rate

        Returns:
            float: second value

        """
        rt = otio.opentime.from_frames(frames, framerate)
        return otio.opentime.to_seconds(rt)

    @staticmethod
    def _make_sequence_collection(path, otio_range, metadata):
        """
        Make collection from path otio range and otio metadata.

        Args:
            path (str): path to image sequence with `%d`
            otio_range (otio.opentime.TimeRange): range to be used
            metadata (dict): data where padding value can be found

        Returns:
            list: dir_path (str): path to sequence, collection object

        """
        if "%" not in path:
            return None
        file_name = os.path.basename(path)
        dir_path = os.path.dirname(path)
        head = file_name.split("%")[0]
        tail = os.path.splitext(file_name)[-1]
        first, last = pype.lib.otio_range_to_frame_range(otio_range)
        collection = clique.Collection(
            head=head, tail=tail, padding=metadata["padding"])
        collection.indexes.update([i for i in range(first, (last + 1))])
        return dir_path, collection

    @staticmethod
    def _trim_media_range(media_range, source_range):
        """
        Trim input media range with clip source range.

        Args:
            media_range (otio.opentime.TimeRange): available range of media
            source_range (otio.opentime.TimeRange): clip required range

        Returns:
            otio.opentime.TimeRange: trimmed media range

        """
        rw_media_start = otio.opentime.RationalTime(
            media_range.start_time.value + source_range.start_time.value,
            media_range.start_time.rate
        )
        rw_media_duration = otio.opentime.RationalTime(
            source_range.duration.value,
            media_range.duration.rate
        )
        return otio.opentime.TimeRange(
            rw_media_start, rw_media_duration)

    @staticmethod
    def _range_from_frames(start, duration, fps):
        """
        Returns otio time range.

        Args:
            start (int): frame start
            duration (int): frame duration
            fps (float): frame range

        Returns:
            otio.opentime.TimeRange: crated range

        """
        return otio.opentime.TimeRange(
            otio.opentime.RationalTime(start, fps),
            otio.opentime.RationalTime(duration, fps)
        )
