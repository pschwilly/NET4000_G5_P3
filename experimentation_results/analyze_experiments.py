import json
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

BASE_DIR = Path(__file__).resolve().parent

EXPERIMENT_TAG = "random" # or "controlled"

HEURISTIC_ROOT = BASE_DIR / "heuristic"
RL_ROOT = BASE_DIR / "RL"
OUTPUT_DIR = BASE_DIR / "analysis_output" / EXPERIMENT_TAG


def find_results_files(root: Path):
    return sorted(root.glob("*/results.json"))


def load_results(json_path: Path):
    with open(json_path, "r") as f:
        data = json.load(f)

    df = pd.DataFrame(data)
    if df.empty:
        return df

    if "episode" in df.columns:
        df["sample"] = df["episode"]
    else:
        df["sample"] = range(1, len(df) + 1)

    if "ue1_sla_ok" not in df.columns:
        df["ue1_sla_ok"] = df["ue1_throughput_mbps"] >= df["sla_ue1_mbps"]

    if "ue2_sla_ok" not in df.columns:
        df["ue2_sla_ok"] = df["ue2_throughput_mbps"] >= df["sla_ue2_mbps"]

    df["both_sla_ok"] = df["ue1_sla_ok"] & df["ue2_sla_ok"]
    return df


def count_rate_changes(df: pd.DataFrame):
    if len(df) < 2:
        return 0
    ue1_changed = df["rate_ue1_mbit"].diff().ne(0)
    ue2_changed = df["rate_ue2_mbit"].diff().ne(0)
    return int((ue1_changed | ue2_changed).sum())


def compute_metrics(df: pd.DataFrame, controller: str, run_name: str):
    metrics = {
        "controller": controller,
        "run_name": run_name,
        "samples": len(df),
        "ue1_sla_success_pct": 100 * df["ue1_sla_ok"].mean(),
        "ue2_sla_success_pct": 100 * df["ue2_sla_ok"].mean(),
        "both_sla_success_pct": 100 * df["both_sla_ok"].mean(),
        "avg_ue1_throughput_mbps": df["ue1_throughput_mbps"].mean(),
        "avg_ue2_throughput_mbps": df["ue2_throughput_mbps"].mean(),
        "avg_rate_ue1_mbit": df["rate_ue1_mbit"].mean(),
        "avg_rate_ue2_mbit": df["rate_ue2_mbit"].mean(),
        "rate_changes": count_rate_changes(df),
    }

    if "reward" in df.columns:
        metrics["avg_reward"] = df["reward"].mean()

    if "epsilon" in df.columns:
        metrics["final_epsilon"] = df["epsilon"].iloc[-1]

    return metrics


def summarize_runs(root: Path, controller: str):
    rows = []
    files = find_results_files(root)
    dataframes =[]
    for file in files:
        df = load_results(file)
        if df.empty:
            continue
        rows.append(compute_metrics(df, controller, file.parent.name))
        dataframes.append((file, df))
    return pd.DataFrame(rows), files


def plot_bar_comparison(summary_df: pd.DataFrame, metric: str, ylabel: str, output_path: Path):
    grouped = summary_df.groupby("controller")[metric].mean()

    plt.figure(figsize=(7, 5))
    plt.bar(grouped.index, grouped.values)
    plt.ylabel(ylabel)
    plt.title(f"{ylabel} by Controller")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()


def plot_boxplot(summary_df: pd.DataFrame, metric: str, ylabel: str, output_path: Path):
    heuristic_vals = summary_df[summary_df["controller"] == "Heuristic"][metric]
    rl_vals = summary_df[summary_df["controller"] == "RL"][metric]

    plt.figure(figsize=(7, 5))
    plt.boxplot([heuristic_vals, rl_vals], labels=["Heuristic", "RL"])
    plt.ylabel(ylabel)
    plt.title(f"{ylabel} Distribution")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()


def plot_example_run(df: pd.DataFrame, controller: str, run_name: str, output_dir: Path):
    # Throughput plot
    plt.figure(figsize=(10, 5))
    plt.plot(df["sample"], df["ue1_throughput_mbps"], label="UE1 Throughput")
    plt.plot(df["sample"], df["ue2_throughput_mbps"], label="UE2 Throughput")
    plt.axhline(df["sla_ue1_mbps"].iloc[0], linestyle="--", label="UE1 SLA")
    plt.axhline(df["sla_ue2_mbps"].iloc[0], linestyle="--", label="UE2 SLA")
    plt.xlabel("Sample")
    plt.ylabel("Measured Throughput (Mbps)")
    plt.title(f"{controller} - {run_name} - Throughput")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / f"{controller}_{run_name}_throughput.png")
    plt.close()

    # Rate plot
    plt.figure(figsize=(10, 5))
    plt.plot(df["sample"], df["rate_ue1_mbit"], label="UE1 Rate")
    plt.plot(df["sample"], df["rate_ue2_mbit"], label="UE2 Rate")
    plt.xlabel("Sample")
    plt.ylabel("Allocated Rate (Mbit)")
    plt.title(f"{controller} - {run_name} - Allocated Rates")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / f"{controller}_{run_name}_rates.png")
    plt.close()

    # RL-only plots
    if "reward" in df.columns:
        plt.figure(figsize=(10, 5))
        plt.plot(df["sample"], df["reward"], label="Reward")
        plt.xlabel("Episode")
        plt.ylabel("Reward")
        plt.title(f"{controller} - {run_name} - Reward")
        plt.legend()
        plt.tight_layout()
        plt.savefig(output_dir / f"{controller}_{run_name}_reward.png")
        plt.close()

    if "epsilon" in df.columns:
        plt.figure(figsize=(10, 5))
        plt.plot(df["sample"], df["epsilon"], label="Epsilon")
        plt.xlabel("Episode")
        plt.ylabel("Epsilon")
        plt.title(f"{controller} - {run_name} - Epsilon")
        plt.legend()
        plt.tight_layout()
        plt.savefig(output_dir / f"{controller}_{run_name}_epsilon.png")
        plt.close()


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    heur_summary, heur_runs = summarize_runs(HEURISTIC_ROOT, "Heuristic")
    rl_summary, rl_runs = summarize_runs(RL_ROOT, "RL")

    summary_df = pd.concat([heur_summary, rl_summary], ignore_index=True)

    if summary_df.empty:
        print("No results.json files found.")
        return

    summary_csv = OUTPUT_DIR / "run_summary.csv"
    summary_df.to_csv(summary_csv, index=False)

    grouped = summary_df.groupby("controller").mean(numeric_only=True)
    grouped_csv = OUTPUT_DIR / "controller_averages.csv"
    grouped.to_csv(grouped_csv)

    print("\n=== Per-run Summary ===")
    print(summary_df.to_string(index=False))

    print("\n=== Controller Averages ===")
    print(grouped.to_string())

    # Comparison graphs
    plot_bar_comparison(
        summary_df,
        "both_sla_success_pct",
        "Both SLAs Met (%)",
        OUTPUT_DIR / "both_sla_success_bar.png"
    )

    plot_bar_comparison(
        summary_df,
        "rate_changes",
        "Average Rate Changes",
        OUTPUT_DIR / "rate_changes_bar.png"
    )

    plot_boxplot(
        summary_df,
        "both_sla_success_pct",
        "Both SLAs Met (%)",
        OUTPUT_DIR / "both_sla_success_boxplot.png"
    )

    # Generate example plots for every run
    for file, df in heur_files:
        plot_example_run(df, "Heuristic", file.parent.name, OUTPUT_DIR)

    for file, df in rl_files:
            plot_example_run(df, "RL", file.parent.name, OUTPUT_DIR)

    print(f"\nAnalysis complete. Files saved in:\n{OUTPUT_DIR}")


if __name__ == "__main__":
    main()
