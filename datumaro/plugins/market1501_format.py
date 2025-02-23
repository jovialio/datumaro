# Copyright (C) 2020-2021 Intel Corporation
#
# SPDX-License-Identifier: MIT

from distutils.util import strtobool
import os
import os.path as osp
import re

from datumaro.components.converter import Converter
from datumaro.components.extractor import DatasetItem, Extractor, Importer
from datumaro.util.image import find_images


class Market1501Path:
    QUERY_DIR = 'query'
    BBOX_DIR = 'bounding_box_'
    IMAGE_EXT = '.jpg'
    PATTERN = re.compile(r'^(-?\d+)_c(\d+)s(\d+)_(\d+)_(\d+)(.*)')
    LIST_PREFIX = 'images_'
    UNKNOWN_ID = -1
    ATTRIBUTES = ['person_id', 'camera_id', 'track_id', 'frame_id', 'bbox_id']

class Market1501Extractor(Extractor):
    def __init__(self, path):
        if not osp.isdir(path):
            raise NotADirectoryError(
                "Can't open folder with annotation files '%s'" % path)

        self._path = path
        super().__init__()

        subsets = {}
        for p in os.listdir(path):
            pf = osp.join(path, p)

            if p.startswith(Market1501Path.BBOX_DIR) and osp.isdir(pf):
                subset = p.replace(Market1501Path.BBOX_DIR, '')
                subsets[subset] = pf

            if p.startswith(Market1501Path.LIST_PREFIX) and osp.isfile(pf):
                subset = p.replace(Market1501Path.LIST_PREFIX, '')
                subset = osp.splitext(subset)[0]
                subsets[subset] = pf

            if p.startswith(Market1501Path.QUERY_DIR) and osp.isdir(pf):
                subset = Market1501Path.QUERY_DIR
                subsets[subset] = pf

        self._items = []
        for subset, subset_path in subsets.items():
            self._items.extend(list(
                self._load_items(subset, subset_path).values()))

    def __iter__(self):
        yield from self._items

    def _load_items(self, subset, subset_path):
        items = {}

        paths = []
        if osp.isfile(subset_path):
            with open(subset_path, encoding='utf-8') as f:
                for line in f:
                    paths.append(osp.join(self._path, line.strip()))
        else:
            paths = list(find_images(subset_path, recursive=True))

        for image_path in sorted(paths):
            item_id = osp.splitext(osp.normpath(image_path))[0]
            if osp.isabs(image_path):
                item_id = osp.relpath(item_id, self._path)
            item_id = item_id.split(osp.sep, maxsplit=1)[1]

            attributes = {}
            search = Market1501Path.PATTERN.search(osp.basename(item_id))
            if search:
                attribute_values = search.groups()[0:5]
                attributes = {
                    'person_id': attribute_values[0],
                    'camera_id': int(attribute_values[1]) - 1,
                    'track_id': int(attribute_values[2]),
                    'frame_id': int(attribute_values[3]),
                    'bbox_id': int(attribute_values[4]),
                    'query': subset == Market1501Path.QUERY_DIR
                }

                custom_name = search.groups()[5]
                if custom_name:
                    item_id = osp.join(osp.dirname(item_id), custom_name)

            item = items.get(item_id)
            if item is None:
                item = DatasetItem(id=item_id, subset=subset, image=image_path,
                    attributes=attributes)
                items[item_id] = item

        return items

class Market1501Importer(Importer):
    @classmethod
    def find_sources(cls, path):
        for dirname in os.listdir(path):
            if dirname.startswith((Market1501Path.BBOX_DIR,
                    Market1501Path.QUERY_DIR, Market1501Path.LIST_PREFIX)):
                return [{'url': path, 'format': Market1501Extractor.NAME}]

class Market1501Converter(Converter):
    DEFAULT_IMAGE_EXT = Market1501Path.IMAGE_EXT

    def _make_dir_name(self, item):
        dirname = Market1501Path.BBOX_DIR + item.subset
        query = item.attributes.get('query')
        if query is not None and isinstance(query, str):
            query = strtobool(query)
        if query:
            dirname = Market1501Path.QUERY_DIR
        return dirname

    def apply(self):
        for subset_name, subset in self._extractor.subsets().items():
            annotation = ''
            used_frames = {}

            for item in subset:
                dirname = self._make_dir_name(item)

                image_name = item.id
                pid = item.attributes.get('person_id')
                match = Market1501Path.PATTERN.fullmatch(item.id)
                if not match and pid:
                    cid = int(item.attributes.get('camera_id', 0)) + 1
                    tid = int(item.attributes.get('track_id', 1))
                    bbid = int(item.attributes.get('bbox_id', 0))
                    fid = int(item.attributes.get('frame_id',
                        max(used_frames.get((pid, cid, tid), [-1])) + 1))
                    image_name = osp.join(osp.dirname(image_name),
                        f'{pid}_c{cid}s{tid}_{fid:06d}_{bbid:02d}')

                image_path = self._make_image_filename(item,
                    name=image_name, subdir=dirname)
                if self._save_images and item.has_image:
                    self._save_image(item, osp.join(self._save_dir, image_path))

                attrs = Market1501Path.PATTERN.search(image_name)
                if attrs:
                    attrs = attrs.groups()
                    used_frames.setdefault(attrs[0:2], []).append(int(attrs[3]))
                annotation += '%s\n' % image_path

            annotation_file = osp.join(self._save_dir,
                Market1501Path.LIST_PREFIX + subset_name + '.txt')
            with open(annotation_file, 'w', encoding='utf-8') as f:
                f.write(annotation)
