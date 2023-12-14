#!/usr/bin/env python3

import os
import re
import sys
import json
from threading import local
import time
from urllib import response
import requests
import json
import queue
import urllib.parse
import logging
from tqdm import tqdm
import shutil
import signal
import concurrent.futures

USE_PROXY = False

logging.basicConfig(level=logging.INFO)
parser_logger = logging.getLogger("myparser")
parser_logger.setLevel(logging.INFO)
http_logger = logging.getLogger("myhttp")
http_logger.setLevel(logging.INFO)

PROXIES = dict(http='socks5://127.0.0.1:7890',
               https='socks5://127.0.0.1:7890') if USE_PROXY else {}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:105.0) Gecko/20100101 Firefox/105.0',
    'Accept': 'application/json',
    'Accept-Encoding': 'gzip, deflate',
    'Accept-Language': 'en-US,en;q=0.5',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'same-origin',
    'Sec-Fetch-User': '?1'
}

def http_get(url, log_start=None, headers=HEADERS, retry=10, sleep_sec=1):
    if log_start:
        logging.info(log_start)
    for i in range(retry):
        try:
            http_logger.debug(f'try to get page: {url}')
            res= requests.get(url, timeout=10, headers=headers,
                               proxies=PROXIES, verify=True)
            res.encoding = 'utf-8'
            #print(res.text)
            #print(res.apparent_encoding)
            return res
        except BaseException as e:
            http_logger.warning(
                f'[x] Failed: {url}, retry={i+1}/{retry}')
            time.sleep(sleep_sec+i)
    http_logger.error(f'Failed to get page: {url}')
    return None

def http_download(url, output_path, log_start=None, remove_if_err=False, show_progress=False, headers=HEADERS, retry=10, sleep_sec=1):
    if log_start:
        logging.info(log_start)
    for i in range(retry):
        try:
            http_logger.debug(f'try to download: {url}')
            res = requests.get(url, stream=True, allow_redirects=True, timeout=10, headers=headers,
                               proxies=PROXIES, verify=True)
            total_size_in_bytes = int(
                res.headers.get('content-length', 0))
            if not show_progress:
                with open(output_path, 'wb') as f:
                    for chunk in res.iter_content(chunk_size=8192):
                        f.write(chunk)
            else:
                with open(output_path, "wb") as f:
                    with tqdm.wrapattr(res.raw, "read", total=total_size_in_bytes, desc="Downloading", colour='green') as r_raw:
                        shutil.copyfileobj(r_raw, f)
                http_logger.info(f'Downloaded: {os.path.getsize(output_path)} bytes, total: {total_size_in_bytes} bytes')
            if os.path.exists(output_path):
                if os.path.getsize(output_path) == total_size_in_bytes:
                    return True
        except BaseException as e:
            http_logger.warning(
                f'[x] Failed: {url}, retry={i+1}/{retry}')
            time.sleep(sleep_sec+i)
    http_logger.error(f'Failed to download: {url}')
    if remove_if_err:
        if os.path.exists(output_path):
            os.remove(output_path)
    return False

def read_plain_urls(path):
    with open(path, 'r') as f:
        return f.readlines()

def write_plain_urls(urls, file):
    with open(file, 'w') as f:
        for url in urls:
            f.write(f'{url}\n')

default_executor = None
def signal_handler(sig, frame):
    logging.warning('You pressed Ctrl+C!')
    if default_executor:
        logging.info(f'Tasks remaining in executor.queue: {default_executor._work_queue.qsize()} to cancel.')
        default_executor.shutdown(False, cancel_futures=True)
        logging.warning(f'The default_executor has been shutdown..')
    # do something here

DEFAULT_CREATORS_FILE='kemono-db/creators.json'
DEFAULT_POSTS_DIR='kemono-db/posts'
# DEFAULT_POSTS_DATA_DIR='kemono-data/posts'
DEFAULT_POSTS_DATA_DIR='/Volumes/left-2T/down/kemono-data/posts'

def save_creators(creators, creators_file=DEFAULT_CREATORS_FILE):
    par_dir = os.path.dirname(os.path.abspath(creators_file))
    if not os.path.exists(par_dir):
        os.makedirs(par_dir)
    with open(creators_file, 'w') as f:
        json.dump(creators, f, indent=2, ensure_ascii=False)
        f.write('\n')

def load_creators(creators_file=DEFAULT_CREATORS_FILE):
    if not os.path.exists(creators_file):
        return None
    with open(creators_file, 'r') as f:
        actor = json.load(f)
    return actor

def make_post_data_dir(creator_name, post, data_dir=DEFAULT_POSTS_DATA_DIR):
    service_dir = os.path.join(data_dir, post["service"])
    user_dir = os.path.join(service_dir, f'{creator_name}-{post["user"]}')
    title = post["title"].replace('/', '-')
    post_dir = os.path.join(user_dir, f'{title}-{post["id"]}')
    if not os.path.exists(post_dir):
        os.makedirs(post_dir)
    return post_dir

def save_creator_posts(creator, posts, posts_dir=DEFAULT_POSTS_DIR):
    if not os.path.exists(posts_dir):
        os.makedirs(posts_dir)
    post_file = os.path.join(posts_dir, f'{creator["service"]}-{creator["id"]}_posts.json')
    with open(post_file, 'w') as f:
        json.dump(posts, f, indent=2, ensure_ascii=False)
        f.write('\n')

def load_creator_posts(creator, posts_dir=DEFAULT_POSTS_DIR):
    post_file = os.path.join(posts_dir, f'{creator["service"]}-{creator["id"]}_posts.json')
    if not os.path.exists(post_file):
        return None
    with open(post_file, 'r') as f:
        posts = json.load(f)
    return posts

class UrlParser:

    _actor_id_pattern = re.compile(r'movies.html\?a=(\w+)')
    _movie_id_pattern = re.compile(r'movie.html\?id=(\w+)')
    _url_root_pattern = re.compile(r'(https://[^/]+)/')
    _url_path_pattern = re.compile(r'(https://[^\?]+)')

    @staticmethod
    def makeAPI_getCreatorPosts(service, creatorId, offset=0, url_root='https://kemono.su/api/v1'):
        return f'{url_root}/{service}/user/{creatorId}?o={offset}'
    
    def makeDownloads(path, url_root='https://kemono.su'):
        if path.startswith('/'):
            return f'{url_root}{path}'
        else:
            return f'{url_root}/{path}'

    @staticmethod
    def parse_actor_id(url):
        pats = re.findall(UrlParser._actor_id_pattern, url)
        parser_logger.debug(pats)
        return pats[0]

    @staticmethod
    def parse_movie_id(url):
        pats = re.findall(UrlParser._movie_id_pattern, url)
        parser_logger.debug(pats)
        return pats[0]

    @staticmethod
    def parse_url_root(url):
        pats = re.findall(UrlParser._url_root_pattern, url)
        parser_logger.debug(pats)
        return pats[0]

    @staticmethod
    def parse_url_path(url):
        pats = re.findall(UrlParser._url_path_pattern, url)
        parser_logger.debug(pats)
        return pats[0]
    
    @staticmethod
    def parse_url_file(url):
        return url.split('/')[-1].split('?')[0]
    
    @staticmethod
    def parse_file_ext(file):
        return file.split('.')[-1]
    
    @staticmethod
    def get_full_url(url_root, relative_path):
        if relative_path.startswith('http'):
            return relative_path
        return f'{url_root}{relative_path}' if relative_path.startswith('/') else f'{url_root}/{relative_path}'
    
    @staticmethod
    def get_actor_url(url_path, actor_id):
        return f'{url_path}?a={actor_id}'
    
class KemonoAPIClient:

    @staticmethod
    def pull_creator_posts(creator, new_only=True):
        if not creator:
            logging.error('creator is None')
            return None
        old_posts = load_creator_posts(creator)
        if not old_posts:
            old_posts = []
        all_posts = {}
        for post in old_posts:
            all_posts[post['id']] = post
        
        offset = 0
        new_posts = []
        while True:
            api_url = UrlParser.makeAPI_getCreatorPosts(creator['service'], creator['id'], offset)
            # parser_logger.debug(f'api_url: {api_url}')
            
            logging.info(f'[P] {creator["name"]}-{creator["id"]}: Parsing {api_url}')
            res = http_get(api_url)
            if not res:
                logging.info(f'[P] {creator["name"]}-{creator["id"]}: no more posts parsed.')
                break
            ret = json.loads(res.text)
            if len(ret) == 0:
                logging.info(f'[P] {creator["name"]}-{creator["id"]}: no more posts parsed.')
                break
            # print(ret)
            new_post_cnt = 0
            for post in ret:
                # print(post)
                id = post['id']
                if not id in all_posts:
                    new_post_cnt += 1
                    new_posts.append(post)
                
                all_posts[id] = post

            logging.info(f'[P] {creator["name"]}-{creator["id"]}: posts (new/parsed): {new_post_cnt}/{len(ret)}')
            if new_only and new_post_cnt < len(ret):
                break
            offset += len(ret)

        logging.info(f'[P] {creator["name"]}-{creator["id"]}: Parsed {len(all_posts)} posts in total.')
        save_creator_posts(creator, list(all_posts.values()))
        
        if new_only:
            return new_posts
        else:
            return list(all_posts.values())
    
    def sync_posts(creator, posts, do_download=True):
        if not creator or not posts:
            logging.error('creator or posts is None.')
            return
        
        logging.info(f'[P] {creator["name"]}-{creator["id"]}: Syncing {len(posts)} posts:')
        i = 0
        todos = {}
        for post in posts:
            i += 1
            downloads = []
            todown = []
            post_data_dir = make_post_data_dir(creator['name'], post)
            # print(post_data_dir)
            post_file = post['file']
            if 'path' in post_file:
                downloads.append({
                    "remote": UrlParser.makeDownloads(post_file['path']),
                    "local": os.path.join(post_data_dir, post_file['name'])
                })
            if 'attachments' in post:
                for attachment in post['attachments']:
                    downloads.append({
                        "remote": UrlParser.makeDownloads(attachment['path']),
                        "local": os.path.join(post_data_dir, attachment['name'])
                })
            for download in downloads:
                if not os.path.exists(download['local']):
                    todown.append(download)

            logging.info(f'[{i}/{len(posts)}] files (to-down/parsed): {len(todown)}/{len(downloads)}: {post["title"]}-{post["id"]}')
            todos[post['id']] = todown

            if do_download:
                for download in todown:
                    http_download(download['remote'], download['local'], show_progress=True)
            
        return todos
        

def test():
    parser_logger.setLevel(logging.DEBUG)
    http_logger.setLevel(logging.DEBUG)
    creator = load_creators()[0]
    posts_todo = load_creator_posts(creator)
    # posts_todo = KemonoAPIClient.pull_creator_posts(creator, new_only=False)
    KemonoAPIClient.sync_posts(creator, posts_todo, do_download=False)

    pass
    # cnt = 0
    # while True:
    #     cnt += 1

if __name__ == '__main__':
    # signal.signal(signal.SIGINT, signal_handler)  
    # signal.signal(signal.SIGTERM, signal_handler)

    if len(sys.argv) > 1:
        arg = sys.argv[1].strip()
        print(f'[==] Parsed arg: {arg}')
        creators = load_creators()
        if arg.startswith('fetch'):
            ret = {}
            for creator in creators:
                posts = KemonoAPIClient.pull_creator_posts(creator, new_only=True)
                ret[creator["name"]] = posts if posts else []
            i = 0
            for key in ret:
                value = ret[key]
                i += 1
                print(f'[Fetch][{i}/{len(creators)}] {len(value)} new posts: {key}')
        elif arg.startswith('pull'):
            for creator in creators:
                posts = KemonoAPIClient.pull_creator_posts(creator, new_only=True)
                KemonoAPIClient.sync_posts(creator, posts, do_download=True)
        elif arg.startswith('scan'):
            ret = {}
            for creator in creators:
                posts = load_creator_posts(creator)
                todos = KemonoAPIClient.sync_posts(creator, posts, do_download=False)
                ret[creator["name"]] = todos if todos else {}
            i = 0
            for key in ret:
                value = ret[key]
                todo = 0
                for todown in value.values():
                    if len(todown) > 0:
                        todo += 1
                i += 1
                print(f'[Scan][{i}/{len(creators)}] posts (to-fix/all): {todo}/{len(value)} {key}')
        elif arg.startswith('download'):
            for creator in creators:
                posts = load_creator_posts(creator)
                KemonoAPIClient.sync_posts(creator, posts, do_download=True)
        elif arg.startswith('sync'):
            for creator in creators:
                posts = KemonoAPIClient.pull_creator_posts(creator, new_only=False)
                KemonoAPIClient.sync_posts(creator, posts, do_download=True)
        else:
            print(f'[X] Unsupported input arg, exit..')
    else:
        print(f'[==] No arg found, processing default operations..')
        test()
   