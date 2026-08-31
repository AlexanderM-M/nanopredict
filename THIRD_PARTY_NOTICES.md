# Third-party data notices

The packaged `nanodx_capper_hg38.tsv.gz` target table was generated from:

- the [nanoDx](https://gitlab.com/pesk/nanoDx) `Capper_et_al_NN.pkl` feature set
  and `crossNN/mapping/450K.csv` coordinates at commit
  `7f2579aa1e120a6057628c289467643e65fb0e4d`; nanoDx is distributed under the
  GNU General Public License v3.0;
- the UCSC Genome Browser `hg19ToHg38.over.chain.gz` assembly mapping.

The exact source hashes, mapped/unmapped counts, and generated-table hash are
recorded in `src/nanopredict/data/nanodx_targets_metadata.json`. The reproducible
conversion utility is `tools/build_nanodx_targets.py`.
