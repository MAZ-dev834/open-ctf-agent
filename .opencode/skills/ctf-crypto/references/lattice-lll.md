# Lattice / LLL Quick Notes

## When to use
- Hidden number problem, partial nonce leaks, small roots, subset-sum style constructions.

## Sage Template (preferred)
```python
from sage.all import *

B = Matrix(ZZ, [
    # rows ...
])
B = B.LLL()
for row in B.rows():
    # interpret candidate
    pass
```

## fpylll Template (Python)
```python
from fpylll import IntegerMatrix, LLL

M = IntegerMatrix.from_matrix([
    # rows ...
])
LLL.reduction(M)
for i in range(M.nrows):
    row = [int(M[i, j]) for j in range(M.ncols)]
```

## Notes
- Normalize scaling so the target short vector is truly short.
- Verify candidates with original equations; do not assume first vector is solution.
