import io

import numpy as np
import pandas as pd

from rugby_league_pricing.database.connection import get_connection


with get_connection() as connection:
    blob = connection.execute(
        """
        SELECT probability_matrix
        FROM historical_score_matrices
        ORDER BY as_of_date DESC
        LIMIT 1
        """
    ).fetchone()[0]

matrix = np.load(io.BytesIO(blob), allow_pickle=False)

df = pd.DataFrame(
    matrix,
    index=range(matrix.shape[0]),
    columns=range(matrix.shape[1]),
)

print(df)