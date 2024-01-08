## Usage
```
python kemono.py [fetch | pull | scan | download | sync | wait]
```

- `fetch`: call kemono API to get `latest` posts of creator and save response to local db file;
- `pull`: `fetch` and download attachments of posts;
- `scan`: find and print missing attachments of posts;
- `download`: `scan` and download missing attachments;
- `sync`: call kemono API to get `whole` posts of creator and download them all;

## Docker
 see [mate60max/kemono-dl](https://hub.docker.com/repository/docker/mate60max/kemono-dl).