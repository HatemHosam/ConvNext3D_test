import json
import os
import shutil
import subprocess
import zipfile
from collections import OrderedDict

import pandas as pd
from joblib import Parallel
from joblib import delayed

if not os.path.exists('data/temp'):
    os.mkdir('data/temp')
if not os.path.exists('data/kinetics600'):
    os.mkdir('data/kinetics600')
if not os.path.exists('data/temp/kinetics600'):
    os.mkdir('data/temp/kinetics600')

kinetics_train_split = zipfile.ZipFile('data/kinetics_600_train (1).zip')
kinetics_train_split.extractall('data/temp/kinetics600')
kinetics_train_split.close()

kinetics_val_split = zipfile.ZipFile('data/kinetics_600_val (1).zip')
kinetics_val_split.extractall('data/temp/kinetics600')
kinetics_val_split.close()

kinetics_test_split = zipfile.ZipFile('data/kinetics_600_test (2).zip')
kinetics_test_split.extractall('data/temp/kinetics600')
kinetics_test_split.close()


def parse_kinetics_annotations(input_csv):
    df = pd.read_csv(input_csv)
    columns = OrderedDict(
        [('youtube_id', 'video-id'), ('time_start', 'start-time'), ('time_end', 'end-time'), ('label', 'label-name')])
    df.rename(columns=columns, inplace=True)
    return df


def create_video_folders(dataset, output_dir, split):
    label_to_dir = {}
    if not os.path.exists(os.path.join(output_dir, split)):
        os.makedirs(os.path.join(output_dir, split))
    for label_name in dataset['label-name'].unique():
        this_dir = os.path.join(output_dir, split, label_name)
        if not os.path.exists(this_dir):
            os.makedirs(this_dir)
        label_to_dir[label_name] = this_dir
    if not os.path.exists('data/kinetics600_labels.txt'):
        with open('data/kinetics600_labels.txt', 'w') as f:
            for label_name in dataset['label-name'].unique():
                f.write(label_name + '\n')

    return label_to_dir


def construct_video_filename(row, label_to_dir, trim_format='%06d'):
    basename = '%s_%s_%s.mp4' % (row['video-id'],
                                 trim_format % row['start-time'],
                                 trim_format % row['end-time'])
    dirname = label_to_dir[row['label-name']]
    output_filename = os.path.join(dirname, basename)
    return output_filename


def download_clip(video_identifier, output_filename, start_time, end_time, num_attempts=5,
                  url_base='https://www.youtube.com/watch?v='):
    """Download a video from youtube if exists and is not blocked.
    arguments:
    ---------
    video_identifier: str
        Unique YouTube video identifier (11 characters)
    output_filename: str
        File path where the video will be stored.
    start_time: float
        Indicates the begining time in seconds from where the video
        will be trimmed.
    end_time: float
        Indicates the ending time in seconds of the trimmed video.
    """
    status = False
    # construct command line for getting the direct video link.
    command = ['youtube-dl',
               '--quiet', '--no-warnings',
               '-f', '18',  # 640x360 h264 encoded video
               '--get-url',
               '"%s"' % (url_base + video_identifier)]
    command = ' '.join(command)
    direct_download_url = None
    attempts = 0
    while True:
        try:
            direct_download_url = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT)
            direct_download_url = direct_download_url.strip().decode('utf-8')
        except subprocess.CalledProcessError as err:
            attempts += 1
            if attempts == num_attempts:
                return status, err.output
            else:
                continue
        break

    # construct command to trim the videos (ffmpeg required).
    command = ['ffmpeg',
               '-ss', str(start_time),
               '-t', str(end_time - start_time),
               '-i', "'%s'" % direct_download_url,
               '-c:v', 'libx264', '-preset', 'ultrafast',
               '-c:a', 'aac',
               '-threads', '1',
               '-loglevel', 'panic',
               '"%s"' % output_filename]
    command = ' '.join(command)
    try:
        output = subprocess.check_output(command, shell=True,
                                         stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as err:
        return status, err.output

    # check if the video was successfully saved.
    status = os.path.exists(output_filename)
    return status, 'Downloaded'


def download_clip_wrapper(row, label_to_dir, trim_format):
    output_filename = construct_video_filename(row, label_to_dir, trim_format)
    clip_id = os.path.basename(output_filename).split('.mp4')[0]
    if os.path.exists(output_filename):
        status = tuple([clip_id, True, 'Exists'])
        return status

    downloaded, log = download_clip(row['video-id'], output_filename, row['start-time'], row['end-time'])
    status = tuple([clip_id, downloaded, log])
    return status


def download_kinetics(input_csv, split, output_dir='data/kinetics600', trim_format='%06d', num_jobs=24):
    # read and parse Kinetics.
    dataset = parse_kinetics_annotations(input_csv)

    # create folders where videos will be saved later.
    label_to_dir = create_video_folders(dataset, output_dir, split)

    # download all clips.
    status_lst = Parallel(n_jobs=num_jobs)(
        delayed(download_clip_wrapper)(row, label_to_dir, trim_format) for i, row in dataset.iterrows())

    # save download report.
    with open('kinetics600_download_report.json', 'w') as fobj:
        fobj.write(json.dumps(status_lst))


download_kinetics('data/temp/kinetics600/kinetics_train.csv', split='train')
download_kinetics('data/temp/kinetics600/kinetics_val.csv', split='val')
download_kinetics('data/temp/kinetics600/kinetics_600_test.csv', split='test')

# clean tmp dir.
shutil.rmtree('data/temp')
