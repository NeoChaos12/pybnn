import os
import logging
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Union, Optional, Tuple, Sequence, Callable
from math import floor
import itertools

from pybnn.utils import AttrDict
from pybnn.utils.universal_utils import standard_pathcheck

_log = logging.getLogger(__name__)

# ################### pybnn data utils ########################

DATASETS_ROOT = "$HOME/UCI_Datasets"
DATADIR = "data"
DATAFILE = "data.txt"
FEATURE_INDEX_FILE = "index_features.txt"
TARGET_INDEX_FILE = "index_target.txt"
TESTSET_INDICES_PREFIX = "index_test_"
TRAINSET_INDICES_PREFIX = "index_train_"


def _read_file_to_numpy_array(root, filename, *args, **kwargs):
    with open(os.path.join(root, filename), 'r') as fp:
        return np.genfromtxt(fp, *args, **kwargs)


def _generate_test_splits_from_local_dataset(name: str, root: str = DATASETS_ROOT, splits: tuple = None):
    """
    Generator function that opens a locally stored dataset and yields the specified train/test splits.
    :param name: Name of the dataset.
    :param root: Root directory containing all datasets.
    :param splits: 2-tuple of starting and ending split indices to be read.
    :return: Generator for tuples (train_X, train_y, test_X, test_y)
    """

    datadir = standard_pathcheck(os.path.join(root, name, DATADIR))

    if splits is None:
        splits = (0, 20)

    _log.debug("Using splits: %s" % str(splits))

    feature_indices = _read_file_to_numpy_array(datadir, FEATURE_INDEX_FILE, dtype=int)
    target_indices = _read_file_to_numpy_array(datadir, TARGET_INDEX_FILE, dtype=int)
    full_dataset = _read_file_to_numpy_array(datadir, DATAFILE, dtype=float)

    for index in range(*splits):
        split_test_indices = _read_file_to_numpy_array(datadir, TESTSET_INDICES_PREFIX + str(index) + '.txt',
                                                       dtype=int)
        split_train_indices = _read_file_to_numpy_array(datadir, TRAINSET_INDICES_PREFIX + str(index) + '.txt',
                                                        dtype=int)

        _log.debug("Using %s test indices, stored in variable of type %s, containing dtype %s" %
                   (str(split_test_indices.shape), type(split_test_indices), split_test_indices.dtype))
        _log.debug("Using %s train indices, stored in variable of type %s, containing dtype %s" %
                   (str(split_train_indices.shape), type(split_train_indices), split_train_indices.dtype))

        testdata = full_dataset[split_test_indices, :]
        traindata = full_dataset[split_train_indices, :]
        yield traindata[:, feature_indices], traindata[:, target_indices], \
              testdata[:, feature_indices], testdata[:, target_indices]


dataloader_args = {
    "boston": {"name": "bostonHousing"},
    "concrete": {"name": "concrete"},
    "energy": {"name": "energy"},
    "kin8nm": {"name": "kin8nm"},
    "naval": {"name": "naval-propulsion-plant"},
    "power": {"name": "power-plant"},
    "protein": {"name": "protein-tertiary-structure"},
    "wine": {"name": "wine-quality-red"},
    "yacht": {"name": "yacht"},
}


# TODO: Define standard AttrDict or namedtuple for dataset configurations
def data_generator(obj_config: AttrDict, numbered=True) -> \
        Union[Tuple[np.ndarray, np.ndarray], Tuple[int, Tuple[np.ndarray, np.ndarray]]]:
    """
    Parses the objective configuration for a named dataset and returns the dataset as X, y arrays.
    :param obj_config: The pre-processed configuration for defining an objective dataset.
    :param numbered: If True (default), returns the index number of the split along with each split.
    :return: Iterator over [index, data] or data
        data is the required dataset as a 2-tuple of numpy arrays, (X, y), where X is the array of observed features
        and y is the array of observed results/labels. This function only returns an iterator.
    """

    dname = obj_config.name.lower()
    generator = _generate_test_splits_from_local_dataset(**dataloader_args[dname], splits=obj_config.splits)
    return enumerate(generator, start=obj_config.splits[0]) if numbered else generator

# ################### emukit-benchmarking data utils ########################

Dataset = Tuple[np.ndarray, np.ndarray, np.ndarray]
RNG_Input = Union[int, np.random.RandomState, None]

class Data:
    def __init__(self, data_folder: Union[str, Path], benchmark_name: str, task_id: int,
                 source_rng_seed: int, evals_per_config: int, extension: str = "csv", iterate_confs: bool = True,
                 iterate_evals: bool = False, emukit_map_func: Callable = None, rng: Union[int, np.random.RandomState, None] = None,
                 train_set_multiplier: int = 10):
        data = Data.read_hpolib_benchmark_data(data_folder=data_folder, benchmark_name=benchmark_name, task_id=task_id,
                                               evals_per_config=evals_per_config, rng_seed=source_rng_seed,
                                               extension=extension)
        self.X_full, self.y_full, self.meta_full = data[:3]
        self.features, self.outputs, self.meta_headers = data[3:]
        if emukit_map_func is not None:
            # We are more interested in keeping the configurations in an emukit-compatible format
            self.X_full = emukit_map_func(self.X_full.reshape((-1, self.X_full.shape[2]))).reshape(self.X_full.shape)

        if rng is None or isinstance(rng, int):
            self.rng = np.random.RandomState(rng)
        else:
            self.rng = rng

        # By default, generate a new split for every update
        self._conf_splits = self._iterate_dataset_configurations(train_size=train_set_multiplier * self.X_full.shape[2],
                                                                 rng=self.rng.randint(0, 1_000_000_000))
        self._eval_splits = None  # Only becomes relevant if iterate_confs is False

        if not iterate_confs:
            _log.debug("Disabling iteration over configuration subsets. Test set will now remain static.")
            train_set, test_set = next(self._conf_splits)
            self._conf_splits = None
            self.train_X, self.train_Y, self.train_meta = None, None, None
            self.test_X, self.test_Y, self.test_meta = test_set
            if iterate_evals:
                _log.debug("Enabling iteration over evaluation subsets. Training set will now iterate over evaluation "
                           "subsets.")
                self._eval_splits = self._generate_evaluation_subsets(dataset=train_set, rng=self.rng)
            else:
                _log.debug("Disabling iteration over evaluation subsets. Training set is now also static.")
                self.train_X, self.train_Y, self.train_meta = next(Data._generate_evaluation_subsets(dataset=train_set,
                                                                                                     rng=self.rng))
        else:
            _log.debug("Training and test sets will iterate over configuration subsets.")

    def update(self):
        """ Update the current data splits. Ideally called in synchrony with Benchmarker's loops. """
        if self._eval_splits is not None:
            _log.debug("Updating training set by iterating over evaluation subsets. Test set is static.")
            self.train_X, self.train_Y, self.train_meta = next(self._eval_splits)
        else:
            if self._conf_splits is not None:
                _log.debug("Updating training and test sets by iterating over configuration subsets.")
                train_data, test_data = next(self._conf_splits)
                self.train_X, self.train_Y, self.train_meta = next(Data._generate_evaluation_subsets(dataset=train_data,
                                                                                                     rng=self.rng))
                self.test_X, self.test_Y, self.test_meta = test_data
            else:
                _log.debug("Training and test sets are static.")
                pass

    @staticmethod
    def read_hpolib_benchmark_data(data_folder: Union[str, Path], benchmark_name: str, task_id: int, rng_seed: int,
                                   evals_per_config: int, extension: str = "csv") -> \
            Tuple[np.ndarray, np.ndarray, np.ndarray, Sequence[str], Sequence[str], Sequence[str]]:
        """
        Reads the relevant data of the given hpolib benchmark from the given folder and returns it as numpy arrays.
        :param data_folder: Path or string
            The folder containing all relevant data files.
        :param benchmark_name: string
            The name of the benchmark.
        :param task_id: int
            The task id used for generating the required data,used to select the correct data file.
        :param rng_seed: int
            The seed that was used for generating the data, used to select the correct data file.
        :param evals_per_config: int
            The number of times each configuration was evaluated.
        :param extension: string
            The file extension.
        :return: X, Y, metadata, feature_names, target_names, meta_headers
            X, Y and metadata will have shapes [N, evals_per_config, Dx], [N, evals_per_config, Dy] and
            [N, evals_per_config, Dz] respectively, whereas feature_names, target_names and meta_headers will have the
            shapes [Nx,], [Ny,] and [Nz,] respectively.
        """

        full_benchmark_name = f"{benchmark_name}_{task_id}_rng{rng_seed}"

        if not isinstance(data_folder, Path):
            data_folder = Path(data_folder).expanduser().resolve()

        data_file = data_folder /  (full_benchmark_name + f"_data.{extension}")
        headers_file = data_folder / (full_benchmark_name + f"_headers.{extension}")
        feature_ind_file = data_folder / (full_benchmark_name + f"_feature_indices.{extension}")
        output_ind_file = data_folder / (full_benchmark_name + f"_output_indices.{extension}")
        meta_ind_file = data_folder / (full_benchmark_name + f"_meta_indices.{extension}")

        with open(headers_file) as fp:
            headers = [line.strip() for line in fp.readlines()]

        with open(feature_ind_file) as fp:
            feature_indices = [int(ind) for ind in fp.readlines()]

        with open(output_ind_file) as fp:
            output_indices = [int(ind) for ind in fp.readlines()]

        with open(meta_ind_file) as fp:
            meta_indices = [int(ind) for ind in fp.readlines()]

        full_dataset = pd.read_csv(data_file, sep=" ", names=headers)
        return full_dataset.iloc[:, feature_indices].to_numpy().reshape((-1, evals_per_config, len(feature_indices))), \
               full_dataset.iloc[:, output_indices].to_numpy().reshape((-1, evals_per_config, len(output_indices))), \
               full_dataset.iloc[:, meta_indices].to_numpy().reshape((-1, evals_per_config, len(meta_indices))), \
               full_dataset.columns[feature_indices].to_numpy(), full_dataset.columns[output_indices].to_numpy(), \
               full_dataset.columns[meta_indices].to_numpy()

    def _iterate_dataset_configurations(self, train_frac: float = None, train_size: int = None,
                                        rng: RNG_Input = None, return_indices: bool = False) -> \
            Tuple[Dataset, Dataset, Optional[Tuple[np.ndarray, np.ndarray]]]:
        """
        Given a dataset consisting of input features of shape [N, i, Dx], output targets of shape [N, i, Dy] and meta
        information of shape [N, i, Dz], where N is the number of configurations, i is the number of evaluations per
        configuration, and Dx, Dy and Dz are the dimensionality of the inputs, targets, and metadata respectively,
        returns a generator that generates a training and a test dataset tuple by choosing distinct configurations.
        Each training dataset contains train_frac * N configurations and all i evaluations, whereas the test dataset
        contains all the evaluations of all remaining configurations. Thus, for a training set containing Nt
        configurations, the input and output arrays would have shapes [Nt, i, Dx] and [Nt, i, Dy] whereas for the
        corresponding test set, they would have shapes [N-Nt, i, Dx] and [N-Nt, i, Dy] respectively.

        :param all_data: (np.ndarray, np.ndarray, np.ndarray)
            The full dataset of input features, output values and meta data, of shapes [N, i, Dx], [N, i, Dy] and
            [N, i, Dz] respectively.
        :param train_frac: float
            The fraction of the total number of configurations N to be used for the training set. All remaining
            configurations are used for the test set. Supercedes train_size.
        :param train_size: int
            The number of configurations to be used for the training dataset. If train_frac is also provided, this is
            ignored.
        :param rng: RandomState, int or None
            A seed for a random number generator or an instance of np.random.RandomState. If None, a random seed value
            is used.
        :param return_indices: bool
            If True, also returns the indices used to construct the training and test sets.
        :return: training set, test set, (optional) train and test indices
        """

        X_full, y_full, meta_full = self.X_full, self.y_full, self.meta_full
        if rng is None or isinstance(rng, int):
            rng = np.random.RandomState(rng)

        if train_frac is None and train_size is None:
            raise RuntimeError("Either 'train_frac' or 'train_size' must be provided.")

        if train_frac is not None:
            train_size = floor(train_frac * X_full.shape[0])

        while (True):
            train_ind = rng.choice(range(X_full.shape[0]), size=train_size, replace=False)
            test_ind = exclude_indices(X_full.shape[0], train_ind)
            train_set = X_full[train_ind, :, :], y_full[train_ind, :, :], meta_full[train_ind, :, :]
            test_set = X_full[test_ind, :, :], y_full[test_ind, :, :], meta_full[test_ind, :, :]

            if return_indices:
                yield train_set, test_set, (train_ind, test_ind)
            else:
                yield train_set, test_set

    @staticmethod
    def _generate_evaluation_subsets(dataset: Dataset, rng: RNG_Input = None) -> Dataset:
        """
        Given a dataset consisting of the input features, outputs and metadata of shapes [N, i, Dx], [N, i, Dy] and
        [N, i, Dz] respectively, generates subsets that randomly select one of i possible evaluations for each of the
        N configurations. Thus, the generator yields a tuple containing 3 arrays of shapes [N, Dx], [N, Dy] and [N, Dz]
        respectively.

        :param dataset:
        :param rng:
        :return:
        """

        X, y, meta = dataset
        if rng is None or isinstance(rng, int):
            rng = np.random.RandomState(rng)

        N, i, Dx = X.shape
        Dy = y.shape[2]
        Dz = meta.shape[2]
        assert N == y.shape[0] and i == y.shape[
            1], "Shape mismatch between input features array of shape %s and output " \
                "array of shape %s." % (str(X.shape), str(y.shape))
        assert N == meta.shape[0] and i == meta.shape[1], "Shape mismatch between input features array of shape %s " \
                                                          "and  metadata array of shape %s." % \
                                                          (str(X.shape), str(meta.shape))
        indices = list(range(i))

        while True:
            choices = rng.choice(indices, size=(X.shape[0], 1, 1), replace=True)
            yield np.take_along_axis(X, choices, axis=1).reshape((N, Dx)), \
                  np.take_along_axis(y, choices, axis=1).reshape((N, Dy)), \
                  np.take_along_axis(meta, choices, axis=1).reshape((N, Dz))

def exclude_indices(npoints: int, indices: Sequence) -> Sequence:
    """ Helper function to generate a sequence of indices that excludes the given indices for a given maximum number of
    indices. """

    all_idx = np.arange(npoints, dtype=int)
    req_idx = np.repeat(True, repeats=npoints)
    req_idx[indices] = False
    return all_idx[req_idx]
