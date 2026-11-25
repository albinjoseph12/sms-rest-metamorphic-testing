# SMS — Semantic Metamorphic Testing of REST APIs with a Persistence-State Oracle

Replication package for the paper of the same name.

## Layout

    sms/                  the technique
      contract.py         OpenAPI analysis: resource model and invariant witnesses
      relations.py        the frozen catalogue of eight metamorphic relations
      gen.py              seeded, schema-driven request synthesis
      state.py            the persistence-state oracle (snapshot / row-level delta)
      engine.py           bootstrap, seeding, instantiation, execution, verdicts
    harness/
      boot.py             prepare / reset / serve / stop for one target
      automanifest.py     automatic manifest synthesis and the boot-repair ladder
    screen.py             the C1-C6 inclusion criteria (frame F1)
    sample_frame.py       eligibility filters and the seeded permutation (frame F2)
    walk.py               walks the permutation, one repository at a time
    run_sms.py            run one target:  run_sms.py <manifest> [--variant] [--seed]
    run_baseline.py       run the Schemathesis baseline under the same conditions
    run_matrix.py         the full target x variant x seed matrix
    analysis/
      triage.py           failing tests -> signatures -> root causes
      baseline_triage.py  the same three-level counting for the baseline
      compare.py          operation-level overlap between the two techniques
      validate.py         independent hand-written reproduction of every root cause
      report.py           writes paper/numbers.json: every number the paper reports
      check_paper.py      re-verifies the manuscript against paper/numbers.json
      figures.py          the three figures
    manifests/            one manifest per target (auto_*.json were synthesised)
    results/              every run: <target>_<variant>_s<seed>.json
    paper/                manuscript, figures, numbers.json, references.json
    setup_env.sh          provisions PostgreSQL and the role the targets use

## Reproducing

    ./setup_env.sh
    python3 run_matrix.py                 # all targets x variants x seeds
    python3 run_baseline.py manifests/realworld.json --budget 900
    python3 analysis/validate.py
    python3 analysis/report.py            # regenerates paper/numbers.json
    python3 analysis/check_paper.py       # verifies the manuscript against it
    python3 analysis/figures.py

`check_paper.py` exits non-zero if any number in the manuscript disagrees with the result files.

## Notes

* The harness never reads a target source file for defect content and never edits one. Only
  deployment configuration is synthesised, and every repair it applies is written into the manifest.
* Targets run without outbound network access. Source executions that fail because a target calls a
  third-party service are recorded as source failures, not as violations.
* Seeds: the frame permutation uses 20260906; runs use 1234, 2718, 3141, 4142, 5772.

---

## Data availability

This repository holds the code, configuration, analysis scripts and figures. The complete raw measurements
(per-run logs and result files) are too large for GitHub and are archived separately on Zenodo with a DOI:
**DOI: to be added on deposit**. Download the archive and extract its `results/` directories into this folder to
re-run the analysis scripts exactly as used for the paper.

## How to cite

The paper is under review. Until it is published, please cite this repository using `CITATION.cff`
(GitHub's "Cite this repository" button).

## License

Code: MIT (see `LICENSE`). Data on Zenodo: CC BY 4.0.
