#!/bin/bash
#SBATCH --job-name=reference-evaluation
#SBATCH --partition=lrd_all_serial
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=reference-evaluation-%j.log

set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit this job with sbatch from the project directory}"

# Use the Python environment activated before sbatch submission.
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-4}"
export MKL_NUM_THREADS="$OMP_NUM_THREADS"
export HF_HUB_OFFLINE=1
export PYTHONUNBUFFERED=1

python3 -m challenge.evaluate_reference \
    --data "${1:-.challenge-uploads}" \
    --evaluation-config "${2:-reference-evaluation.clip.json}"
