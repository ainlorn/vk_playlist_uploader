#!/usr/bin/env python3
import subprocess
import tempfile
import uuid
import argparse
import itertools
import json
import os
import time
import hashlib

import requests
import eyed3
from vkaudiotoken import get_vk_official_token

BASE_URL = 'https://api.vk.com/method/'
FFMPEG_EXECUTABLE = 'ffmpeg'
CONV_FORMATS = ['.flac']
COVER_FILENAMES = ['cover', 'jacket', 'folder']
IMG_FORMATS = ['.jpg', '.jpeg', '.png']
COVER_FILES = list([''.join(i) for i in itertools.product(COVER_FILENAMES, IMG_FORMATS)])
CAPTCHA_SLEEP = 120

_script_dir = os.path.dirname(__file__)
CREDENTIALS_FILE = f'{_script_dir}/creds.json'
TOKEN_FILE = f'{_script_dir}/token.json'
RECURSIVE = False

_sess = requests.session()
_sess.headers.update(
    {'User-Agent': 'VKAndroidApp/6.30-7444 (Android 7.1.1; SDK 25; arm64-v8a; Xiaomi MI8; ru; 1920x1080)',
     'X-VK-Android-Client': 'new'})

_remove = []


class Track:
    def __init__(self, path, artist=None, title=None, disc_num=None, track_num=None, album=None, album_artist=None):
        self.path = path
        self.artist = artist
        self.title = title
        self.disc_num = disc_num
        self.track_num = track_num
        self.album = album
        self.album_artist = album_artist
        self.orig_path = path
        if track_num is None:
            self.track_num = 0
        if disc_num is None:
            self.disc_num = 0
        if artist is None:
            self.artist = 'Unknown artist'
        if title is None:
            self.title = 'Untitled'
        if album is None:
            self.album = 'Untitled album'
        if album_artist is None:
            self.album_artist = self.artist

    def get_filename(self):
        return os.path.splitext(os.path.basename(os.path.normpath(self.orig_path)))[0]

    def __eq__(self, b) -> bool:
        return self.path == b.path

    def __ne__(self, b) -> bool:
        return self.path != b.path

    def __lt__(self, b) -> bool:
        if self.album == b.album:
            if self.disc_num == b.disc_num:
                if self.track_num == b.track_num:
                    if self.artist == b.artist:
                        if self.title == b.title:
                            na = self.get_filename()
                            nb = b.get_filename()
                            if na == nb:
                                return False
                            elif na < nb:
                                return True
                            return False
                        elif self.title < b.title:
                            return True
                        return False
                    elif self.artist < b.artist:
                        return True
                    return False
                elif self.track_num < b.track_num:
                    return True
                return False
            elif self.disc_num < b.disc_num:
                return True
            return False
        elif self.album < b.album:
            return True
        return False

    def __gt__(self, b) -> bool:
        if self.album == b.album:
            if self.disc_num == b.disc_num:
                if self.track_num == b.track_num:
                    if self.artist == b.artist:
                        if self.title == b.title:
                            na = self.get_filename()
                            nb = b.get_filename()
                            if na == nb:
                                return False
                            elif na > nb:
                                return True
                            return False
                        elif self.title > b.title:
                            return True
                        return False
                    elif self.artist > b.artist:
                        return True
                    return False
                elif self.track_num > b.track_num:
                    return True
                return False
            elif self.disc_num > b.disc_num:
                return True
            return False
        elif self.album > b.album:
            return True
        return False

    def __str__(self):
        return f'{self.artist} - {self.title} [{self.album_artist} - {self.album}] ' \
               f'{{{self.disc_num} - {self.track_num}}}'

    def __repr__(self):
        return f'<{self.__str__()}>'


def get_token(login, password):
    token = get_vk_official_token(login, password)
    _id = check_token(token)
    if _id:
        token['id'] = _id
        return token, cred_hash(login, password)
    else:
        raise Exception('Token check failed while acquiring new token')


def save_token(token_file, token, _hash):
    with open(token_file, 'w') as f:
        json.dump({'hash': _hash, 'token': token}, f)


def cred_hash(login, password):
    return hashlib.md5(' '.join((login, password)).encode('utf-8')).hexdigest()


def check_token(token):
    r = vk_request('account.getProfileInfo', token, v='5.130')
    if "error" not in r:
        return r['response']['id']
    else:
        return False


def _post_wrapper(*args, **kwargs):
    retries = 10
    max_sleep = 32
    c_sleep = 1

    while True:
        try:
            r = _sess.post(*args, **kwargs)
            return r
        except requests.exceptions.ConnectionError:
            if retries == 0:
                raise
            print('ERROR: Connection error, retrying in', c_sleep, 'seconds!')
            c_sleep = min(c_sleep * 2, max_sleep)
            retries -= 1


def vk_request(method, token, v, params=None, **kwargs):
    _params = [('access_token', token['token']), ('v', v)]
    for i in kwargs:
        _params.append((i, kwargs[i]))
    if params:
        _params.extend(params)

    _json = _post_wrapper(BASE_URL + method,
                          params=_params).json()
    if 'error' in _json and _json['error']['error_code'] == 14:
        print('WARNING: Captcha needed, waiting', CAPTCHA_SLEEP, 'secs...')
        time.sleep(CAPTCHA_SLEEP)
        return vk_request(method, token, v, params, **kwargs)
    return _json


def conv_to_mp3(old_file, new_file):
    p = subprocess.Popen([FFMPEG_EXECUTABLE, '-i', old_file, '-ab', '320k', '-map_metadata', '0', '-id3v2_version', '3',
                          new_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    p.communicate()
    if p.returncode == 0:
        return True
    return False


def process_mp3(path):
    audiofile = eyed3.load(path)
    disc_num = audiofile.tag.disc_num[0]
    track_num = audiofile.tag.track_num[0]
    artist = audiofile.tag.artist
    album = audiofile.tag.album
    album_artist = audiofile.tag.album_artist
    title = audiofile.tag.title
    if artist is None:
        artist = 'Unknown artist'
    if title is None:
        title = 'Untitled'
    return Track(path, artist, title, disc_num, track_num, album, album_artist)


def process_dir(path, recursive=False):
    if not os.path.exists(path):
        print(path, 'does not exist')
        return
    if not os.path.isdir(path):
        print(path, 'is not a directory')
        return
    tracks = []
    cover = None
    dir_name = os.path.basename(path)

    for file in os.listdir(path):
        _spl = os.path.splitext(file)
        filepath = os.path.join(path, file)
        if os.path.isdir(filepath) and recursive:
            tracks.extend(process_dir(filepath, True)[0])
        elif len(_spl) > 1:
            if _spl[1] == '.mp3':
                tracks.append(process_mp3(filepath))
            elif _spl[1] in CONV_FORMATS:
                new_file = os.path.join(tempfile.gettempdir(), str(uuid.uuid4()) + '.mp3')
                _remove.append(new_file)
                print('Converting', file)
                if conv_to_mp3(filepath, new_file):
                    track = process_mp3(new_file)
                    track.orig_path = filepath
                    tracks.append(track)
                else:
                    print('Convertation of', file, 'failed!')
                    return
            elif (file.lower() in COVER_FILES) or \
                    (file.lower() in [''.join(i) for i in itertools.product((dir_name,), IMG_FORMATS)]):
                cover = os.path.join(path, file)
                print('Found cover image', file)

    tracks.sort()
    if len(tracks) > 0:
        return tracks, cover

    return [], None


def vk_upload_file(url, file, field_name):
    return _post_wrapper(url, files={field_name: open(file, 'rb')}).json()


def upload_track(token, track, group_id=None):
    r = vk_request('audio.getUploadServer', token, '5.130')
    if 'error' in r:
        print(r)
        raise Exception('Error getting upload server')
    upload_url = r['response']['upload_url']

    r = vk_upload_file(upload_url, track.path, 'file')
    if 'error' in r:
        print(r)
        raise Exception('Error uploading file')

    r = vk_request('audio.save', token, '5.130', server=r['server'], audio=r['audio'],
                   hash=r['hash'])
    if 'error' in r:
        if r['error']['error_code'] == 270:
            print('WARNING:', track, 'was removed by copyright holder!')
            return False
        print(r)
        raise Exception('Error saving file')

    owner_id = r['response']['owner_id']
    _id = r['response']['id']

    if group_id:
        r = vk_request('audio.add', token, '5.130', owner_id=owner_id, audio_id=_id, group_id=group_id[1:])
        if 'error' in r:
            print(r)
            raise Exception('Error saving file to group')
        new_id = r['response']

        r = vk_request('execute', token, '5.130', code=f"API.audio.delete({{audio_id:{_id},owner_id:{owner_id}}});")

        return f'{group_id}_{new_id}'
    return f'{token["id"]}_{_id}'


def upload_tracks(token, tracks, cover, group_id=None, hidden=0):
    if group_id:
        owner = group_id
    else:
        owner = token['id']

    desc = ''

    audios = []
    for track in tracks:
        print('Uploading', track)
        audio = upload_track(token, track, group_id)
        if audio:
            audios.append(audio)
        else:
            if not desc:
                desc = 'Missing tracks:\n'
            desc += f'{track.artist} - {track.title}\n'

    t = tracks[len(tracks) - 1]
    album_title = f'{t.album_artist} - {t.album}'

    audios.reverse()
    print('Creating playlist', album_title)
    r = vk_request('execute.savePlaylist', token, '5.149', dialog_id=0, playlist_id=0, title=album_title,
                   description=desc, audio_ids_to_add=','.join(audios), no_discover=hidden, owner_id=owner, func_v=6,
                   save_cover=0)
    if 'error' in r:
        print(r)
        raise Exception('Error creating playlist')
    pid = r['response']['playlist']['id']

    if cover:
        print('Uploading cover...')
        r = vk_request('photos.getAudioPlaylistCoverUploadServer', token, '5.149', playlist_id=pid, owner_id=owner)
        if 'error' in r:
            print(r)
            raise Exception('Error getting cover upload server')
        upload_url = r['response']['upload_url']

        r = vk_upload_file(upload_url, cover, 'photo')
        if 'error' in r:
            print(r)
            raise Exception('Error uploading cover')
        _hash = r['hash']
        photo = r['photo']

        r = vk_request('audio.setPlaylistCoverPhoto', token, '5.149', hash=_hash, photo=photo)
        if 'error' in r:
            print(r)
            raise Exception('Error setting album cover')


def main(directories, group_id, hidden, recursive):
    if not os.path.exists(CREDENTIALS_FILE):
        print('Credentials file does not exist.')
        return

    with open(CREDENTIALS_FILE, 'r') as f:
        _credentials = json.load(f)
    login = _credentials['login']
    password = _credentials['password']

    if os.path.exists(TOKEN_FILE):
        print('Loading token from file...')
        with open(TOKEN_FILE, 'r') as f:
            _token = json.load(f)
        _hash = cred_hash(login, password)

        if _hash != _token['hash']:
            print('Credentials changed, getting new token...')
            token, _hash = get_token(login, password)
            save_token(TOKEN_FILE, token, _hash)
        elif check_token(_token['token']):
            token = _token['token']
        else:
            print('Token check failed, getting new token...')
            token, _hash = get_token(login, password)
            save_token(TOKEN_FILE, token, _hash)
    else:
        print('Getting new token...')
        token, _hash = get_token(login, password)
        save_token(TOKEN_FILE, token, _hash)
    print('Token acquired.')

    for d in directories:
        f = os.path.normpath(d)
        print('Processing', f)
        tracks, cover = process_dir(f, recursive)
        if tracks is not None:
            if len(tracks) > 0:
                upload_tracks(token, tracks, cover, group_id, hidden)
            else:
                print(f, 'does not have audio files.')
        else:
            print('Processing of', f, 'failed!')


if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument('-g', '--group', type=int, metavar='<group_id>',
                            help='upload to group instead of user page')
        parser.add_argument('-c', '--creds', metavar='<creds_path>',
                            help='specify path to credentials file')
        parser.add_argument('-t', '--token', metavar='<token_path>',
                            help='specify path to token file')
        parser.add_argument('-r', '--recursive', action='store_true',
                            help='process directories recursively')
        parser.add_argument('-H', '--hidden', action='store_true',
                            help='hide playlists from search')
        parser.add_argument('dirs', metavar='directory', nargs='*',
                            help='directories to upload')
        args = parser.parse_args()

        _gid = None
        if args.group:
            if args.group < 0:
                _gid = str(args.group)
            else:
                _gid = str(-args.group)
        if args.creds:
            CREDENTIALS_FILE = args.creds
        if args.token:
            TOKEN_FILE = args.token
        _rec = args.recursive
        _hid = 1 if args.hidden else 0

        if len(args.dirs) == 0:
            parser.print_help()
        else:
            main(args.dirs, _gid, _hid, _rec)
    except KeyboardInterrupt:
        print('Exiting...')
    finally:
        for _f in _remove:
            if os.path.exists(_f):
                os.remove(_f)
