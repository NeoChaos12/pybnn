import pandas as pd
from pathlib import Path
from bnnbench.utils import constants as C
import bnnbench.visualization.runhistory as viz
import logging
from bnnbench.bin import _default_log_format, _log

logging.basicConfig(format=_default_log_format)
_log.setLevel(logging.INFO)
viz._log.setLevel(logging.INFO)

root = Path("/home/archit/master_project/experiments/benchmark_data")
source = root
dest = root / "presentation"

# df1 = pd.read_pickle(root / "xgboost_full_hpo" / C.FileNames.tsne_embeddings_dataframe)
# tasks = df1.index.unique("task")

viz.cell_width = 4
viz.cell_height = 4
viz.label_fontsize = 30

# benchmarks = ["paramnet", "xgboost_single_hpo", "xgboost_full_hpo", "synthetic"]
# idx = ["dataset", "task_id", "task_id", "objective"]
# benchmarks = ["paramnet", "xgboost_single_hpo", "synthetic"]
benchmarks = ["xgboost_single_hpo", "xgboost_full_hpo"]
# idx = ["dataset", "task_id", "task_id"]
# benchmarks = ["synthetic"]
# tasks = ['Branin']
# tasks = ['Hartmann3_2']
# tasks = ['Borehole_6']
# benchmarks = ["paramnet"]
# tasks = ['mnist', 'poker']
# benchmarks = ["xgboost_full_hpo"]
tasks = ['167184', '167202']
# benchmarks = ["xgboost_single_hpo"]
# tasks = ['167188', '167156', '167184', '167202']
# tasks = ['167188', '167156']
# tasks = None
# prefix = "AllTasks"
# prefix = "4Tasks"
# prefix = "2Tasks"

# labels = ['task', 'model', 'rng_offset', 'iteration']
main_df = None
for bench in benchmarks:
    print("Reading df from %s" % bench)
    prefix = f"{bench}_CommonTasks"
    dfpath = source / bench
    df: pd.DataFrame = pd.read_pickle(dfpath / C.FileNames.tsne_embeddings_dataframe)
    if tasks is not None:
        df = df[df.index.get_level_values("task").isin(tasks, level="task")].reindex(tasks, level="task", axis=0)
    viz.plot_embeddings(embedded_data=df, indices=[["model", "task", ], None], save_data=True, output_dir=dest,
                        file_prefix=prefix, suptitle=None, palette='RdYlGn_r')
    del(df)

