from importlib import import_module
import sys
from io import BytesIO
import pprint
import json
import pprint
from math import ceil, sqrt
import os
from random import random, randrange, shuffle
import numpy as np
from PIL import Image
from shapeworld import util
from shapeworld.world import World
from shapeworld.realizers import CaptionRealizer


def dataset(dtype=None, name=None, language=None, config=None):
    # explain type = 'load', 'mixer', possibilities, e.g. with ',', or with ';'?
    assert config is None or isinstance(config, dict) or isinstance(config, str)
    assert dtype is None or isinstance(dtype, str)
    assert name is None or isinstance(name, str)
    load = mix = False
    if config is not None and isinstance(config, str):
        if config[:5] == 'load(' and config[-1] == ')':
            load = True
            config = config[5:-1]
        elif config[:4] == 'mix(' and config[-1] == ')':
            mix = True
            config = config[4:-1]
        assert not load or not mix
        # mix default config when names list
        if mix and not os.path.isfile(config):
            return DatasetMixer(datasets=config.split(','))
        if load and os.path.isdir(config):
            print(f'CONFIG: {config}')
            assert dtype and name
            if language is None:
                directory = os.path.join(config, dtype, name)
                config = os.path.join(config, '{}-{}.json'.format(dtype, name))
            else:
                directory = os.path.join(config, '{}-{}'.format(dtype, language), name)
                config = os.path.join(config, '{}-{}-{}.json'.format(dtype, language, name))
        else:
            assert os.path.isfile(config)
            directory = os.path.dirname(config)
        with open(config, 'r') as filehandle:
            config = json.load(fp=filehandle)
        if load and 'directory' not in config:
            config['directory'] = directory
    if load:
        dataset = LoadedDataset(specification=config)
        assert dtype is None or dtype == dataset.type
        assert name is None or name == dataset.name
        assert language is None or language == dataset.language
        return dataset
    if mix:
        dataset = DatasetMixer(**config)
        assert dtype is None or dtype == dataset.type
        return dataset
    if config is not None:
        if 'type' in config:
            if dtype is None:
                dtype = config['type']
            else:
                assert dtype == config['type']
        if 'name' in config:
            if name is None:
                name = config['name']
            else:
                assert name == config['name']
        if 'language' in config:
            if language is None:
                language = config['language']
            else:
                assert language == config['language']
    assert dtype and name
    module = import_module('shapeworld.datasets.{}.{}'.format(dtype, name))
    dclass = module.dataset
    if config is None:
        config = dict()
    if language is not None:
        config['language'] = language
    dataset = dclass(**config)
    return dataset


def alternatives_type(value_type):
    if len(value_type) > 5 and value_type[:5] == 'alts(' and value_type[-1] == ')':
        return value_type[5:-1], True
    else:
        return value_type, False


class Dataset(object):

    def __init__(self, world_size, vectors=None, vocabularies=None, language=None):
        assert self.type and self.name
        assert 'alternatives' not in self.values or self.values['alternatives'] == 'int'
        assert all(not alternatives_type(value_type=value_type)[1] for value_type in self.values.values()) or 'alternatives' in self.values
        if isinstance(world_size, int):
            self.world_size = world_size
        else:
            self.world_size = tuple(world_size)
        self.vectors = vectors
        self.vocabularies = dict()
        if vocabularies is not None:
            for name, vocabulary in vocabularies.items():
                vocabulary = {word: index for index, word in enumerate(vocabulary, 1) if word != '' and word != '[UNKNOWN]'}
                vocabulary[''] = 0
                vocabulary['[UNKNOWN]'] = len(vocabulary)
                self.vocabularies[name] = vocabulary
        self.language = language

    def __str__(self):
        if self.language is None:
            return '{} {}'.format(self.type, self.name)
        else:
            return '{} {} ({})'.format(self.type, self.name, self.language)

    @property
    def name(self):
        name = self.__class__.__name__
        lowercase_name = list()
        for n, char in enumerate(name):
            if char.isupper():
                if n > 0:
                    lowercase_name.append('_')
                lowercase_name.append(char.lower())
            else:
                lowercase_name.append(char)
        return ''.join(lowercase_name)

    @property
    def type(self):
        raise NotImplementedError

    @property
    def values(self):
        raise NotImplementedError

    def specification(self):
        specification = {'type': self.type, 'name': self.name, 'values': self.values}
        if isinstance(self.world_size, int):
            specification['world_size'] = self.world_size
        else:
            specification['world_size'] = list(self.world_size)
        if self.vectors:
            specification['vectors'] = self.vectors
        if self.vocabularies:
            specification['vocabularies'] = self.vocabularies
        if self.language:
            specification['language'] = self.language
        return specification

    @property
    def world_shape(self):
        if isinstance(self.world_size, int):
            return (self.world_size, self.world_size, 3)
        else:
            return (self.world_size[0], self.world_size[1], 3)

    def vector_shape(self, value_name):
        return (self.vectors.get(value_name),)

    def vocabulary_size(self, value_type):
        if self.vocabularies is None or value_type not in self.vocabularies:
            return -1
        else:
            return len(self.vocabularies[value_type])

    def vocabulary(self, value_type):
        if self.vocabularies is None or value_type not in self.vocabularies:
            return None
        else:
            return [word for word, _ in sorted(self.vocabularies[value_type].items(), key=(lambda kv: kv[1]))]

    def zero_batch(self, n, include_model=False, alternatives=False):
        batch = dict()
        for value_name, value_type in self.values.items():
            value_type, alts = alternatives_type(value_type=value_type)
            if alternatives and alts:
                if value_type == 'int':
                    batch[value_name] = [[] for _ in range(n)]
                elif value_type == 'float':
                    batch[value_name] = [[] for _ in range(n)]
                elif value_type == 'vector(int)' or value_type in self.vocabularies:
                    batch[value_name] = [[np.zeros(shape=self.vector_shape(value_name), dtype=np.int32)] for _ in range(n)]
                elif value_type == 'vector(float)':
                    batch[value_name] = [[np.zeros(shape=self.vector_shape(value_name), dtype=np.float32)] for _ in range(n)]
                elif value_type == 'model' and include_model:
                    batch[value_name] = [[] for _ in range(n)]
                elif value_type == 'str_list':
                    batch[value_name] = ["" for _ in range(n)]
                elif value_type == 'str_list_list':
                    batch[value_name] = [[] for _ in range(n)]
                elif value_type == 'str_list_list_list':
                    batch[value_name] = [[] for _ in range(n)]
            else:
                if value_type == 'int' and (value_name != 'alternatives' or alternatives):
                    batch[value_name] = np.zeros(shape=(n,), dtype=np.int32)
                elif value_type == 'float':
                    batch[value_name] = np.zeros(shape=(n,), dtype=np.float32)
                elif value_type == 'vector(int)' or value_type in self.vocabularies:
                    batch[value_name] = np.zeros(shape=((n,) + self.vector_shape(value_name)), dtype=np.int32)
                elif value_type == 'vector(float)':
                    batch[value_name] = np.zeros(shape=((n,) + self.vector_shape(value_name)), dtype=np.float32)
                elif value_type == 'world':
                    batch[value_name] = np.zeros(shape=((n,) + self.world_shape), dtype=np.float32)
                elif value_type == 'model' and include_model:
                    batch[value_name] = [None] * n
                elif value_type == 'str_list':
                    batch[value_name] = ["" for _ in range(n)]
                elif value_type == 'str_list_list':
                    batch[value_name] = [[] for _ in range(n)]
                elif value_type == 'str_list_list_list':
                    batch[value_name] = [[] for _ in range(n)]
        return batch

    def generate(self, n, mode=None, noise_range=None, include_model=False, alternatives=False):  # mode: None, 'train', 'validation', 'test'
        raise NotImplementedError

    def iterate(self, n, mode=None, noise_range=None, include_model=False, alternatives=False):
        while True:
            yield self.generate(n=n, mode=mode, noise_range=noise_range, include_model=include_model, alternatives=alternatives)

    def get_html(self, generated):
        return None

    def serialize(self, path, generated, additional=None, filename=None, archive=None, concat_worlds=False, html=False):
        assert not additional or all(value_name not in self.values for value_name in additional)
        if not os.path.isdir(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))

        with util.Archive(path=path, mode='w', archive=archive) as write_file:
            for value_name, value in generated.items():
                if self.values[value_name] == 'skip':
                    # print(f'Skipping serializing {value_name}')
                    pass
                else:
                    # print(f'Serializing {value_name}')
                    Dataset.serialize_value(
                        value=value,
                        value_name=value_name,
                        value_type=self.values[value_name],
                        write_file=write_file,
                        concat_worlds=concat_worlds,
                        id2word=self.vocabulary(value_type=self.values[value_name])
                    )
                if additional:
                    for value_name, (value, value_type) in additional.items():
                        Dataset.serialize_value(
                            value=value,
                            value_name=value_name,
                            value_type=value_type,
                            write_file=write_file,
                            concat_worlds=concat_worlds,
                            id2word=self.vocabulary(value_type=self.values[value_name])
                        )
                if html:
                    html = self.get_html(generated=generated)
                    assert html is not None
                    write_file(filename='data.html', value=html)

    @staticmethod
    def serialize_value(value, value_name, value_type, write_file, concat_worlds=False, id2word=None):
        value_type, alts = alternatives_type(value_type=value_type)
        if value_type == 'int':
            if alts:
                value = '\n'.join(';'.join(str(int(x)) for x in xs) for xs in value) + '\n'
            else:
                value = '\n'.join(str(int(x)) for x in value) + '\n'
            write_file(value_name + '.txt', value)
        elif value_type == 'float':
            if alts:
                value = '\n'.join(';'.join(str(float(x)) for x in xs) for xs in value) + '\n'
            else:
                value = '\n'.join(str(float(x)) for x in value) + '\n'
            write_file(value_name + '.txt', value)
        elif value_type == 'vector(int)' or value_type == 'vector(float)':
            if alts:
                value = '\n'.join(';'.join(','.join(str(x) for x in vector) for vector in vectors) for vectors in value) + '\n'
            else:
                value = '\n'.join(','.join(str(x) for x in vector) for vector in value) + '\n'
            write_file(value_name + '.txt', value)
        elif value_type == 'world':
            if concat_worlds:
                size = ceil(sqrt(len(value)))
                worlds = []
                for y in range(ceil(len(value) / size)):
                    if y < len(value) // size:
                        worlds.append(np.concatenate([value[y * size + x] for x in range(size)], axis=1))
                    else:
                        worlds.append(np.concatenate([value[y * size + x] for x in range(len(value) % size)] + [np.zeros_like(a=value[0]) for _ in range(-len(value) % size)], axis=1))
                worlds = np.concatenate(worlds, axis=0)
                image = World.get_image(world_array=worlds)
                image_bytes = BytesIO()
                image.save(image_bytes, format='bmp')
                write_file(value_name + '.bmp', image_bytes.getvalue(), binary=True)
                image_bytes.close()
            else:
                for n in range(len(value)):
                    image = World.get_image(world_array=value[n])
                    image_bytes = BytesIO()
                    image.save(image_bytes, format='bmp')
                    write_file('{}-{}.bmp'.format(value_name, n), image_bytes.getvalue(), binary=True)
                    image_bytes.close()
        elif value_type == 'model':
            value = json.dumps(obj=value, indent=2, sort_keys=True)
            write_file(value_name + '.json', value)
        elif value_type == 'str_list_list':
            value = '\n'.join(' || '.join(x for x in elem) for elem in value) + '\n'
            write_file(value_name + '.txt', value)
        elif value_type == 'str_list_list_list':
            value = '\n'.join(' || '.join(', '.join(x for x in it) for it in elem) for elem in value) + '\n'
            write_file(value_name + '.txt', value)
        elif value_type == 'str_list':
            value = '\n'.join(x for x in value) + '\n'
            write_file(value_name + '.txt', value)
        else:
            assert id2word
            if alts:
                value = '\n\n'.join('\n'.join(' '.join(id2word[word_id] for word_id in words if word_id) for words in words_alts) for words_alts in value) + '\n\n'
            else:
                value = '\n'.join(' '.join(id2word[word_id] for word_id in words if word_id) for words in value) + '\n'
            write_file(value_name + '.txt', value)

    @staticmethod
    def deserialize_value(value_name, value_type, read_file, num_concat_worlds=0, word2id=None):
        value_type, alts = alternatives_type(value_type=value_type)
        if value_type == 'int':
            value = read_file(value_name + '.txt')
            if alts:
                value = [[int(x) for x in xs.split(';')] for xs in value.split('\n')[:-1]]
            else:
                value = [int(x) for x in value.split('\n')[:-1]]
            return value
        elif value_type == 'float':
            value = read_file(value_name + '.txt')
            if alts:
                value = [[float(x) for x in xs.split(';')] for xs in value.split('\n')[:-1]]
            else:
                value = [float(x) for x in value.split('\n')[:-1]]
            return value
        elif value_type == 'vector(int)':
            value = read_file(value_name + '.txt')
            if alts:
                value = [[[int(x) for x in vector.split(',')] for vector in vectors.split(';')] for vectors in value.split('\n')[:-1]]
            else:
                value = [[int(x) for x in vector.split(',')] for vector in value.split('\n')[:-1]]
            return value
        elif value_type == 'vector(float)':
            value = read_file(value_name + '.txt')
            if alts:
                value = [[[float(x) for x in vector.split(',')] for vector in vectors.split(';')] for vectors in value.split('\n')[:-1]]
            else:
                value = [[float(x) for x in vector.split(',')] for vector in value.split('\n')[:-1]]
            return value
        elif value_type == 'world':
            if num_concat_worlds:
                size = ceil(sqrt(num_concat_worlds))
                image_bytes = read_file(value_name + '.bmp', binary=True)
                assert image_bytes is not None
                image_bytes = BytesIO(image_bytes)
                image = Image.open(image_bytes)
                worlds = World.from_image(image)
                height = worlds.shape[0] // ceil(num_concat_worlds / size)
                assert worlds.shape[0] % ceil(num_concat_worlds / size) == 0
                width = worlds.shape[1] // size
                assert worlds.shape[1] % size == 0
                value = []
                for y in range(ceil(num_concat_worlds / size)):
                    for x in range(size if y < num_concat_worlds // size else num_concat_worlds % size):
                        value.append(worlds[y * height: (y + 1) * height, x * width: (x + 1) * width, :])
            else:
                value = []
                n = 0
                while True:
                    image_bytes = read_file('{}-{}.bmp'.format(value_name, n), binary=True)
                    if image_bytes is None:
                        break
                    image_bytes = BytesIO(image_bytes)
                    image = Image.open(image_bytes)
                    value.append(World.from_image(image))
                    n += 1
            return value
        elif value_type == 'model':
            value = read_file(value_name + '.json')
            value = json.loads(s=value)
            return value
        elif value_type == 'str_list':
            value = read_file(value_name + '.txt')
            value = [caption for caption in value.split('\n')[:-1]]
            return value
        elif value_type == 'str_list_list':
            value = read_file(value_name + '.txt')
            value = [[caption for caption in cap_list.split(' || ')] for cap_list in value.split('\n')[:-1]]
            return value
        elif value_type == 'str_list_list_list':
            value = read_file(value_name + '.txt')
            value = [[[it for it in items.split(', ')] for items in pred_item.split(' || ')] for pred_item in value.split('\n')[:-1]]
            return value
        else:
            assert word2id
            value = read_file(value_name + '.txt')
            if alts:
                value = [[[word2id[word] for word in words.split(' ')] for words in words_alts.split('\n')] for words_alts in value.split('\n\n')[:-1]]
            else:
                value = [[word2id[word] for word in words.split(' ')] for words in value.split('\n')[:-1]]
            return value


class LoadedDataset(Dataset):

    def __init__(self, specification):
        self._type = specification.pop('type')
        self._name = specification.pop('name')
        self._values = specification.pop('values')
        self.archive = specification.pop('archive', None)
        self.include_model = specification.pop('include_model', False)
        self.num_concat_worlds = specification.pop('num_concat_worlds', 0)
        self.directory = specification.pop('directory')
        self._specification = specification

        super(LoadedDataset, self).__init__(world_size=specification.pop('world_size'), vectors=specification.pop('vectors', None), vocabularies=specification.pop('vocabularies', None), language=specification.pop('language', None))

        self.per_part = True
        self.part_once = False
        self.parts = dict()
        for root, dirs, files in os.walk(self.directory):
            if root == self.directory:
                assert not files
                assert len(dirs) <= 4 and 'train' in dirs and 'validation' in dirs and 'test' in dirs and (len(dirs) == 3 or 'tf-records' in dirs)
            elif root[len(self.directory) + 1:] in ('train', 'validation', 'test', 'tf-records'):
                mode = root[len(self.directory) + 1:]
                if dirs:
                    assert all(d[:4] == 'part' and d[4:].isdigit() for d in dirs)
                    # print(dirs, files)
                    assert not files
                    self.parts[mode] = [os.path.join(root, d) for d in dirs]
                else:
                    assert all(f[:4] == 'part' for f in files)
                    self.parts[mode] = [os.path.join(root, f) for f in files]
        assert self.parts
        self.mode = None
        self.loaded = {value_name: [] for value_name, value_type in self.values.items() if value_type != 'model' or self.include_model}
        self.num_instances = 0

    @property
    def name(self):
        return self._name

    @property
    def type(self):
        return self._type

    @property
    def values(self):
        return self._values

    def specification(self):
        specification = super(LoadedDataset, self).specification()
        specification.update(self._specification)
        return specification

    def __getattr__(self, name):
        try:
            return super(LoadedDataset, self).__getattr__(name=name)
        except AttributeError:
            if name in self._specification:
                return self._specification[name]
            else:
                raise

    def get_records_paths(self):
        assert 'tf-records' in self.parts
        return self.parts['tf-records']

    def generate(self, n, mode=None, noise_range=None, include_model=False, alternatives=False):
        assert not include_model or self.include_model
        if not self.per_part:
            self.mode = None if mode else 'train'
        while self.mode != mode or self.num_instances < n:
            if self.mode != mode:
                self.mode = mode
                self.loaded = {value_name: [] for value_name, value_type in self.values.items() if value_type not in ('model', 'alts(model)') or self.include_model}
            parts = self.parts[mode]
            part = randrange(len(parts))
            path = parts.pop(part) if self.part_once else parts[part]
            self.num_instances = 0
            with util.Archive(path=path, mode='r', archive=self.archive) as read_file:
                for value_name, value in self.loaded.items():
                    if self.values[value_name] == 'skip':
                        # print(f'Skipping deserializing {value_name}')
                        pass
                    else:
                        # print(f'Deserializing {value_name}')
                        value.extend(Dataset.deserialize_value(
                            value_name=value_name,
                            value_type=self.values[value_name],
                            read_file=read_file,
                            num_concat_worlds=self.num_concat_worlds,
                            word2id=self.vocabularies.get(self.values[value_name])
                        ))
                        if self.num_instances:
                            assert len(value) == self.num_instances
                        else:
                            self.num_instances = len(value)
        batch = self.zero_batch(n, include_model=include_model, alternatives=alternatives)
        for i in range(n):
            index = randrange(self.num_instances)
            self.num_instances -= 1
            for value_name, value_type in self.values.items():
                if value_type in ('model', 'alts(model)') and not self.include_model:
                    continue
                if value_type == 'skip':
                    continue
                value = self.loaded[value_name].pop(index)
                if value_type in self.vocabularies:
                    batch[value_name][i][:len(value)] = value
                elif value_type not in ('model', 'alts(model)') or include_model:
                    batch[value_name][i] = value
        if noise_range is not None and noise_range > 0.0:
            for value_name, value_type in self.values.items():
                if value_type == 'world':
                    noise = np.random.normal(loc=0.0, scale=noise_range, size=((n,) + self.world_shape))
                    mask = (noise < -2.0 * noise_range) + (noise > 2.0 * noise_range)
                    while np.any(a=mask):
                        noise -= mask * noise
                        noise += mask * np.random.normal(loc=0.0, scale=noise_range, size=((n,) + self.world_shape))
                        mask = (noise < -2.0 * noise_range) + (noise > 2.0 * noise_range)
                    worlds = batch[value_name]
                    worlds += noise
                    np.clip(worlds, a_min=0.0, a_max=1.0, out=worlds)
        return batch

    def get_html(self, generated):
        module = import_module('shapeworld.datasets.{}.{}'.format(self.type, self.name))
        dclass = module.dataset
        return dclass.get_html(self, generated=generated)


class DatasetMixer(Dataset):

    # accepts Dataset, config, str
    def __init__(self, datasets, consistent_batches=False, distribution=None, train_distribution=None, validation_distribution=None, test_distribution=None):
        assert len(datasets) >= 1
        for n, dataset in enumerate(datasets):
            if not isinstance(dataset, Dataset):
                datasets[n] = Dataset.dataset(config=dataset)
        assert all(dataset.type == datasets[0].type for dataset in datasets)
        assert all(dataset.language == datasets[0].language for dataset in datasets)
        assert all(dataset.values == datasets[0].values for dataset in datasets)
        assert all(dataset.world_size == datasets[0].world_size for dataset in datasets)
        assert all(sorted(dataset.vectors) == sorted(datasets[0].vectors) for dataset in datasets)
        assert all(sorted(dataset.vocabularies) == sorted(datasets[0].vocabularies) for dataset in datasets)
        # combine vectors and words information
        vectors = {value_name: max(dataset.vectors[value_name] for dataset in datasets) for value_name in datasets[0].vectors}
        vocabularies = dict()
        for name in datasets[0].vocabularies:
            vocabularies[name] = sorted(set(word for dataset in datasets for word in dataset.vocabularies[name]))
        language = datasets[0].language
        super(DatasetMixer, self).__init__(None, vectors=vectors, vocabularies=vocabularies, language=language)
        for dataset in datasets:
            dataset.vectors = self.vectors
            dataset.vocabularies = self.vocabularies
        self.datasets = datasets
        self.consistent_batches = consistent_batches
        assert not distribution or len(distribution) == len(datasets)
        distribution = util.value_or_default(distribution, [1] * len(datasets))
        self.distribution = util.cumulative_distribution(distribution)
        assert bool(train_distribution) == bool(validation_distribution) == bool(test_distribution)
        assert not train_distribution or len(train_distribution) == len(validation_distribution) == len(test_distribution) == len(self.distribution)
        self.train_distribution = util.cumulative_distribution(util.value_or_default(train_distribution, distribution))
        self.validation_distribution = util.cumulative_distribution(util.value_or_default(validation_distribution, distribution))
        self.test_distribution = util.cumulative_distribution(util.value_or_default(test_distribution, distribution))

    @property
    def type(self):
        return self.datasets[0].type

    @property
    def values(self):
        return self.datasets[0].values

    @property
    def world_size(self):
        return self.datasets[0].world_size

    def generate(self, n, mode=None, noise_range=None, include_model=False, alternatives=False):
        if mode is None:
            distribution = self.distribution
        if mode == 'train':
            distribution = self.train_distribution
        elif mode == 'validation':
            distribution = self.validation_distribution
        elif mode == 'test':
            distribution = self.test_distribution
        if self.consistent_batches:
            dataset = util.sample(distribution, self.datasets)
            return dataset.generate(n=n, mode=mode, noise_range=noise_range, include_model=include_model, alternatives=alternatives)
        else:
            batch = self.zero_batch(n, include_model=include_model, alternatives=alternatives)
            for i in range(n):
                dataset = util.sample(distribution, self.datasets)
                generated = dataset.generate(n=1, mode=mode, noise_range=noise_range, include_model=include_model, alternatives=alternatives)
                for value_name, value_type in self.values.items():
                    value = generated[value_name][0]
                    if value_type in self.vocabularies:
                        batch[value_name][i][:len(value)] = value
                    else:
                        batch[value_name][i] = value
        return batch


class ClassificationDataset(Dataset):

    def __init__(self, world_generator, num_classes, multi_class=False, class_count=False):
        super(ClassificationDataset, self).__init__(world_size=world_generator.world_size, vectors=dict(classification=num_classes))
        assert multi_class or not class_count
        self.world_generator = world_generator
        self.num_classes = num_classes
        self.multi_class = multi_class
        self.class_count = class_count

    @property
    def type(self):
        return 'classification'

    @property
    def values(self):
        return dict(world='world', world_model='model', classification='vector(float)')

    def specification(self):
        specification = super(ClassificationDataset, self).specification()
        specification['num_classes'] = self.num_classes
        specification['multi_class'] = self.multi_class
        specification['class_count'] = self.class_count
        return specification

    def get_classes(self, world):  # iterable of classes
        raise NotImplementedError

    def generate(self, n, mode=None, noise_range=None, include_model=False, alternatives=False):
        batch = self.zero_batch(n, include_model=include_model, alternatives=alternatives)
        for i in range(n):
            self.world_generator.initialize(mode=mode)

            while True:
                world = self.world_generator()
                if world is not None:
                    break

            batch['world'][i] = world.get_array(noise_range=noise_range)
            if include_model:
                batch['world_model'][i] = world.model()
            c = None
            for c in self.get_classes(world):
                if self.class_count:
                    batch['classification'][i][c] += 1.0
                else:
                    batch['classification'][i][c] = 1.0
            if not self.multi_class:
                assert c is not None
        return batch

    def get_html(self, generated):
        classifications = generated['classification']
        data_html = list()
        for n, classification in enumerate(classifications):
            data_html.append('<div class="instance"><div class="world"><img src="world-{world}.bmp" alt="world-{world}.bmp"></div><div class="num"><p><b>({num})</b></p></div><div class="classification"><p>'.format(world=n, num=(n + 1)))
            comma = False
            for c, count in enumerate(classification):
                if count == 0.0:
                    continue
                if comma:
                    data_html.append(',&ensp;')
                else:
                    comma = True
                if self.class_count:
                    data_html.append('{count:.0f} &times; class {c}'.format(c=c, count=count))
                else:
                    data_html.append('class {c}'.format(c=c))
            data_html.append('</p></div></div>')
        html = '<!DOCTYPE html><html><head><title>{dtype} {name}</title><style>.data{{width: 100%; height: 100%;}} .instance{{width: 100%; margin-top: 1px; margin-bottom: 1px; background-color: #CCCCCC;}} .world{{height: {world_height}px; display: inline-block; vertical-align: middle;}} .num{{display: inline-block; vertical-align: middle; margin-left: 10px;}} .classification{{display: inline-block; vertical-align: middle; margin-left: 10px;}}</style></head><body><div class="data">{data}</div></body></html>'.format(
            dtype=self.type,
            name=self.name,
            world_height=self.world_shape[0],
            data=''.join(data_html)
        )
        return html


class CaptionAgreementDataset(Dataset):

    INITIALIZE_CAPTIONER = 100

    def __init__(self, world_generator, world_captioner, caption_size, vocabulary, correct_ratio=None, train_correct_ratio=None, validation_correct_ratio=None, test_correct_ratio=None, caption_realizer=None, language=None):
        assert isinstance(caption_size, int) and caption_size > 0
        vocabulary = list(vocabulary)
        assert len(vocabulary) > 0 and vocabulary == sorted(vocabulary)
        self.world_generator = world_generator
        self.world_captioner = world_captioner
        if isinstance(caption_realizer, CaptionRealizer):
            self.caption_realizer = caption_realizer
        else:
            assert caption_realizer is None or isinstance(caption_realizer, str)
            self.caption_realizer = CaptionRealizer.from_name(
                name=util.value_or_default(caption_realizer, 'dmrs'),
                language=util.value_or_default(language, 'english')
            )
        self.world_captioner.set_realizer(self.caption_realizer)
        vocabularies = dict(
            language=vocabulary,
            rpn=sorted(self.world_captioner.rpn_symbols())
        )
        super(CaptionAgreementDataset, self).__init__(
            world_size=world_generator.world_size,
            vectors=dict(
                caption=caption_size,
                caption_rpn=self.world_captioner.rpn_length()
            ),
            vocabularies=vocabularies,
            language=language
        )
        self.correct_ratio = util.value_or_default(correct_ratio, 0.5)
        self.train_correct_ratio = util.value_or_default(train_correct_ratio, self.correct_ratio)
        self.validation_correct_ratio = util.value_or_default(validation_correct_ratio, self.correct_ratio)
        self.test_correct_ratio = util.value_or_default(test_correct_ratio, self.correct_ratio)

    @property
    def type(self):
        return 'agreement'

    @property
    def values(self):
        return dict(world='world', world_model='model', caption='language', caption_length='int', caption_rpn='rpn', caption_rpn_length='int', caption_model='model', agreement='float')

    def generate(self, n, mode=None, noise_range=None, include_model=False, alternatives=False):
        if mode == 'train':
            correct_ratio = self.train_correct_ratio
        elif mode == 'validation':
            correct_ratio = self.validation_correct_ratio
        elif mode == 'test':
            correct_ratio = self.test_correct_ratio
        else:
            correct_ratio = self.correct_ratio

        captioners_proposed = list()
        captioners_used = list()

        rpn2id = self.vocabularies['rpn']
        unknown = rpn2id['[UNKNOWN]']
        rpn_size = self.vector_shape('caption_rpn')[0]

        batch = self.zero_batch(n, include_model=include_model, alternatives=alternatives)
        captions = [None] * n
        for i in range(n):
            # print(i, end=', ', flush=True)
            correct = random() < correct_ratio
            resample = 0
            while True:
                self.world_generator.initialize(mode=mode)
                if resample % self.__class__.INITIALIZE_CAPTIONER == 0:
                    if resample // self.__class__.INITIALIZE_CAPTIONER >= 1:
                        # print('resample captioner')
                        # print(self.world_captioner.correct, self.world_captioner.model())
                        # exit(0)
                        pass
                    while not self.world_captioner.initialize(mode=mode, correct=correct):
                        # print('initialize false')
                        # assert False
                        pass
                    captioner_model = self.world_captioner.model()
                    if captioner_model not in captioners_proposed:
                        captioners_proposed.append(captioner_model)
                    # print(json.dumps(obj=self.world_captioner.model(), indent=2, sort_keys=True))
                    # print(self.world_captioner.captioner, self.world_captioner.correct)

                resample += 1

                while True:
                    world = self.world_generator()
                    if world is not None:
                        break

                caption = self.world_captioner(world=world)
                '''Testing variability of captions'''
               # print(f'20 captions generated for image {i}')
               # cap_eg = caption
               # caps = []
               # for _ in range(20):
               #     self.world_captioner.initialize(mode=mode, correct=correct)
               #     cap_eg = self.world_captioner(world=world)
               #     try:
               #         cap = self.caption_realizer.realize(captions=[cap_eg])
               #         cap = ' '.join([word for word in cap[0]])
               #     except:
               #         print("DMR realizer assertion error")
               #         cap = ""
               #     caps.append(cap)
               # caps = set(caps)
               # print(f'Num distinct captions: {len(caps)}\nCaptions: {caps}')
               # print("==============================================")
                if caption is not None:
                    break
                else:
                    # print('captioner failed')
                    pass

            if captioner_model not in captioners_used:
                captioners_used.append(captioner_model)

            captions[i] = caption

            batch['world'][i] = world.get_array(noise_range=noise_range)
            batch['agreement'][i] = float(correct)

            rpn = caption.reverse_polish_notation()
            assert len(rpn) <= rpn_size
            for k, rpn_symbol in enumerate(rpn):
                assert rpn_symbol in rpn2id
                batch['caption_rpn'][i][k] = rpn2id.get(rpn_symbol, unknown)
            batch['caption_rpn_length'][i] = len(rpn)

            if include_model:
                batch['world_model'][i] = world.model()
                batch['caption_model'][i] = caption.model()

        word2id = self.vocabularies['language']
        unknown = word2id['[UNKNOWN]']
        caption_size = self.vector_shape('caption')[0]

        unused_words = set(word2id)  # for assert
        unused_words.remove('')
        unused_words.remove('[UNKNOWN]')
        missing_words = set()  # for assert
        max_caption_size = caption_size  # for assert

        captions = self.caption_realizer.realize(captions=captions)
        for i, caption in enumerate(captions):
            if len(caption) > caption_size:
                if len(caption) > max_caption_size:
                    max_caption_size = len(caption)
                continue
            for k, word in enumerate(caption):
                if word in word2id:
                    unused_words.discard(word)
                else:
                    missing_words.add(word)
                    continue
                batch['caption'][i][k] = word2id.get(word, unknown)
            batch['caption_length'][i] = len(caption)

        if len(captioners_used) < len(captioners_proposed):
            # print('More captioner models proposed than used: {} > {}'.format(len(captioners_proposed), len(captioners_used)))
            # for captioner_model in captioners_proposed:
            #     if captioner_model not in captioners_used:
            #         print(json.dumps(obj=captioner_model, indent=2, sort_keys=True))
            pass

        # if len(unused_words) > 0:
        #     print('Words unused in vocabulary: \'{}\''.format('\', \''.join(sorted(unused_words))))
        # if max_caption_size < caption_size:
        #     print('Caption size smaller than max size: {} < {}'.format(max_caption_size, caption_size))
        if len(missing_words) > 0:
            print('Words missing in vocabulary: \'{}\''.format('\', \''.join(sorted(missing_words))))
        if max_caption_size > caption_size:
            print('Caption size exceeds max size: {} > {}'.format(max_caption_size, caption_size))
        assert not missing_words and max_caption_size <= caption_size

        return batch

    def get_html(self, generated):
        id2word = self.vocabulary(value_type='language')
        captions = generated['caption']
        caption_lengths = generated['caption_length']
        agreements = generated['agreement']
        data_html = list()
        for n, (caption, caption_length, agreement) in enumerate(zip(captions, caption_lengths, agreements)):
            if agreement == 1.0:
                agreement = 'correct'
            elif agreement == 0.0:
                agreement = 'incorrect'
            else:
                agreement = 'ambiguous'
            data_html.append('<div class="{agreement}"><div class="world"><img src="world-{world}.bmp" alt="world-{world}.bmp"></div><div class="num"><p><b>({num})</b></p></div><div class="caption"><p>{caption}</p></div></div>'.format(
                agreement=agreement,
                world=n,
                num=(n + 1),
                caption=util.tokens2string(id2word[word] for word in caption[:caption_length])
            ))
        html = '<!DOCTYPE html><html><head><title>{dtype} {name}</title><style>.data{{width: 100%; height: 100%;}} .correct{{width: 100%; margin-top: 1px; margin-bottom: 1px; background-color: #BBFFBB;}} .incorrect{{width: 100%; margin-top: 1px; margin-bottom: 1px; background-color: #FFBBBB;}} .ambiguous{{width: 100%; margin-top: 1px; margin-bottom: 1px; background-color: #FFFFBB;}} .world{{height: {world_height}px; display: inline-block; vertical-align: middle;}} .num{{display: inline-block; vertical-align: middle; margin-left: 10px;}} .caption{{display: inline-block; vertical-align: middle; margin-left: 10px;}}</style></head><body><div class="data">{data}</div></body></html>'.format(
            dtype=self.type,
            name=self.name,
            world_height=self.world_shape[0],
            data=''.join(data_html)
        )
        return html


class TextSelectionDataset(CaptionAgreementDataset):

    INITIALIZE_CAPTIONER = 100

    def __init__(self, world_generator, world_captioner, caption_size, vocabulary, correct_ratio=None, train_correct_ratio=None, validation_correct_ratio=None, test_correct_ratio=None, caption_realizer=None, language=None, number_texts=10):
        '''All initially generated captions should agree with the image. Distractors randomly selected as non identical descriptions of other images'''
        super(TextSelectionDataset, self).__init__(world_generator, world_captioner, caption_size, vocabulary, correct_ratio=1.0, train_correct_ratio=1.0, validation_correct_ratio=1.0, test_correct_ratio=1.0, caption_realizer=caption_realizer, language=language)
        self.number_texts = number_texts
        vocab = self.vocabularies['language']
        self.idx2word = {}
        for k, v in vocab.items():
            self.idx2word[v] = k

    @property
    def values(self):
        return dict(world='world', world_model='model', caption='language', caption_length='int', caption_rpn='rpn', caption_rpn_length='int', caption_model='model', agreement='float', pred_items='str_list_list', caption_str = 'str_list', texts='skip', texts_str='str_list_list', target='int')

    def idx_2_captions(self, captions):
        captions_str = []
        for i in range(captions.shape[0]):
            caption = ""
            for j in range(captions.shape[1]):
                caption += self.idx2word[captions[i][j]] + " "
            captions_str.append(caption)
        return captions_str

    def generate(self, n, mode=None, noise_range=None, include_model=False, alternatives=False):
        print(f'\nBatch size: {n}, Number of texts: {self.number_texts}')
        batch = super(TextSelectionDataset, self).generate(n, mode=mode, noise_range=noise_range, include_model=include_model, alternatives=alternatives)
        assert np.sum(batch['agreement']) == batch['agreement'].shape[0]
        batch = self.add_caption_lists(batch, n)
        print('================ Example prediction items, caption, and final texts  =================')
        for i in range(min(10, n)):
            print(f'i: {i}, pred items: {batch["pred_items"][i]}, caption: {batch["caption_str"][i]}\ntexts: {batch["texts_str"][i]}')
        return batch

    def add_caption_lists(self, batch, n):
        batch = self.extract_prediction_items(batch, n)
        max_len = batch['caption'].shape[1]
        '''Get indices of other texts'''
        '''There must be enough data'''
        assert n >= 10 * self.number_texts
        idxs = np.zeros((n, self.number_texts)).astype(int)
        print(f'Batch targets shape: {batch["target"].shape}')
        for i, item in enumerate(batch['pred_items']):
            idxs[i] = self.get_caption_idxs(i, item, batch['pred_items'])
            batch['target'][i] = np.where(idxs[i]==i)[0]
            #print(idxs[i])
            #print(batch['target'][i])
        print("Selection of text idxs...")
        print(idxs[:10])
        batch['texts'] = np.zeros((n, self.number_texts, max_len))
        print(f'Batch texts shape: {batch["texts"].shape}')
        '''Get relevant texts given indices'''
        for i in range(n):
            batch['texts'][i] = batch['caption'][idxs[i]]
            captions = self.idx_2_captions(batch['texts'][i])
            batch['texts_str'][i].extend(captions)
        '''Convert captions to strings'''
        batch['caption_str'] = self.idx_2_captions(batch['caption'])
        assert len(batch['caption_str']) == n
        return batch

    def get_caption_idxs(self, i, item, pred_items):
        idxs = [i]
        n = len(pred_items)
        candidate_idxs = np.random.randint(0, n, size=self.number_texts * 2).tolist()
        while len(idxs) < self.number_texts:
           if len(candidate_idxs) == 0:
               candidate_idxs = np.random.randint(0, n, size=self.number_texts * 2).tolist()
           idx = candidate_idxs.pop()
           if (idx != i) and (set(pred_items[idx]) != set(item)):
               idxs.append(idx)
        shuffle(idxs)
        idxs = np.asarray(idxs).astype(int)
        return idxs

    def get_prediction_item(self, caption_model):
        items = []
        #pprint.pprint(caption_model)
        if 'component' in caption_model:
            if caption_model['component'] == 'EntityType':
                vals = caption_model['value']
                for k in vals:
                    items.append(vals[k]['value'])
        if 'body' in caption_model:
            comp = caption_model['body']['value']['component']
            if comp == 'EntityType':
                vals = caption_model['body']['value']['value']
                for k in vals:
                    items.append(vals[k]['value'])
            elif comp == 'Attribute':
                items.append(caption_model['body']['value']['value'])
            assert caption_model['restrictor']['component'] == 'EntityType'
            res = caption_model['restrictor']['value']
            for k in res:
                items.append(res[k]['value'])
        items = list(set(items))
        #print(f'Items: {items}')
        assert len(items) > 0
        return items

    def extract_prediction_items(self, batch, n):
        for i, cap_model in enumerate(batch['caption_model']):
            pred_items = self.get_prediction_item(cap_model)
            batch['pred_items'][i].extend(pred_items)
        return batch

    def get_html(self, generated):
        id2word = self.vocabulary(value_type='language')
        captions = generated['caption']
        caption_lengths = generated['caption_length']
        texts_lists = generated['texts_str']
        agreements = generated['agreement']
        pred_items = generated['pred_items']
        targets = generated['target']
        data_html = list()
        for n, (caption, texts, agreement, caption_length, pred, t) in enumerate(zip(captions, texts_lists,  agreements, caption_lengths, pred_items, targets)):
            if agreement == 1.0:
                agreement = 'correct'
            elif agreement == 0.0:
                agreement = 'incorrect'
            else:
                agreement = 'ambiguous'
            pred_item = "Prediction items: "
            for p in pred:
                pred_item += p + ", "
            cap = "Caption: " + util.tokens2string(id2word[word] for word in caption[:caption_length])
            cap += " Target idx: " + str(t)
            text = 'Texts: '
            for t in texts:
                text += t + ", "
            data_html.append('<div class="{agreement}"><div class="world"><img src="world-{world}.bmp" alt="world-{world}.bmp"></div><div class="num"><p><b>({num})</b></p></div><div class="caption"><p>{pred_item}</p><p>{caption}</p><p>{text}</p></div></div>'.format(
                agreement=agreement,
                world=n,
                num=(n + 1),
                pred_item=pred_item,
                caption=cap,
                text=text
            ))
        html = '<!DOCTYPE html><html><head><title>{dtype} {name}</title><style>.data{{width: 100%; height: 100%;}} .correct{{width: 100%; margin-top: 1px; margin-bottom: 1px; background-color: #BBFFBB;}} .incorrect{{width: 100%; margin-top: 1px; margin-bottom: 1px; background-color: #FFBBBB;}} .ambiguous{{width: 100%; margin-top: 1px; margin-bottom: 1px; background-color: #FFFFBB;}} .world{{height: {world_height}px; display: inline-block; vertical-align: middle;}} .num{{display: inline-block; vertical-align: middle; margin-left: 10px;}} .caption{{display: inline-block; vertical-align: middle; margin-left: 10px;}}</style></head><body><div class="data">{data}</div></body></html>'.format(
            dtype=self.type,
            name=self.name,
            world_height=self.world_shape[0],
            data=''.join(data_html)
        )
        return html


class TextSelectionMultiShapeDataset(TextSelectionDataset):

    INITIALIZE_CAPTIONER = 100
    
    @property
    def values(self):
        return dict(world='world', world_model='model', caption='language', caption_length='int', caption_rpn='rpn', caption_rpn_length='int', caption_model='model', agreement='float', pred_items='str_list_list_list', caption_str = 'str_list', texts='skip', texts_str='str_list_list', target='int')


    def extract_prediction_items(self, batch, n):
        for i, cap_model in enumerate(batch['world_model']):
            pred_items = self.get_prediction_item(cap_model)
            batch['pred_items'][i].extend(pred_items)
        return batch

    def get_prediction_item(self, world_model):
        items = []
        entities = world_model['entities']
        for e in entities:
            shape = e['shape']['name']
            color = e['color']['name']
            items.append([shape, color])
        assert len(items) > 0
        return items
    
    def get_caption_idxs(self, i, item, pred_items):
        idxs = [i]
        n = len(pred_items)
        candidate_idxs = np.random.randint(0, n, size=self.number_texts * 2).tolist()
        while len(idxs) < self.number_texts:
           if len(candidate_idxs) == 0:
               candidate_idxs = np.random.randint(0, n, size=self.number_texts * 2).tolist()
           idx = candidate_idxs.pop()
           flag = True
           if (idx == i):
               flag = False
           for p in pred_items[idx]:
               for it in item:
                   if set(p) == set(it):
                       flag = False
           if flag:
               idxs.append(idx)
        shuffle(idxs)
        idxs = np.asarray(idxs).astype(int)
        return idxs
    
    def get_html(self, generated):
        id2word = self.vocabulary(value_type='language')
        captions = generated['caption']
        caption_lengths = generated['caption_length']
        texts_lists = generated['texts_str']
        agreements = generated['agreement']
        pred_items = generated['pred_items']
        targets = generated['target']
        data_html = list()
        for n, (caption, texts, agreement, caption_length, pred, t) in enumerate(zip(captions, texts_lists,  agreements, caption_lengths, pred_items, targets)):
            if agreement == 1.0:
                agreement = 'correct'
            elif agreement == 0.0:
                agreement = 'incorrect'
            else:
                agreement = 'ambiguous'
            pred_item = "Prediction items: "
            for p in pred:
                pred_item += "["
                for elem in p:
                    pred_item += elem + ", "
                pred_item += "], "
            cap = "Caption: " + util.tokens2string(id2word[word] for word in caption[:caption_length])
            cap += " Target idx: " + str(t)
            text = 'Texts: '
            for t in texts:
                text += t + ", "
            data_html.append('<div class="{agreement}"><div class="world"><img src="world-{world}.bmp" alt="world-{world}.bmp"></div><div class="num"><p><b>({num})</b></p></div><div class="caption"><p>{pred_item}</p><p>{caption}</p><p>{text}</p></div></div>'.format(
                agreement=agreement,
                world=n,
                num=(n + 1),
                pred_item=pred_item,
                caption=cap,
                text=text
            ))
        html = '<!DOCTYPE html><html><head><title>{dtype} {name}</title><style>.data{{width: 100%; height: 100%;}} .correct{{width: 100%; margin-top: 1px; margin-bottom: 1px; background-color: #BBFFBB;}} .incorrect{{width: 100%; margin-top: 1px; margin-bottom: 1px; background-color: #FFBBBB;}} .ambiguous{{width: 100%; margin-top: 1px; margin-bottom: 1px; background-color: #FFFFBB;}} .world{{height: {world_height}px; display: inline-block; vertical-align: middle;}} .num{{display: inline-block; vertical-align: middle; margin-left: 10px;}} .caption{{display: inline-block; vertical-align: middle; margin-left: 10px;}}</style></head><body><div class="data">{data}</div></body></html>'.format(
            dtype=self.type,
            name=self.name,
            world_height=self.world_shape[0],
            data=''.join(data_html)
        )
        return html
