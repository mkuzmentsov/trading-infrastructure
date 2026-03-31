import pandas as pd
df = pd.read_csv("outputs/features.csv")
print("Duplicate timestamps:", df["timestamp"].duplicated().sum())
print("Label distribution:\n", df["target_dir_1bar"].value_counts())
