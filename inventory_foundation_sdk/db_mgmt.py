"""Classes and functions for managing access to the databases"""

# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/10_db_mgmt.ipynb.

# %% auto 0
__all__ = ['get_db_credentials', 'insert_multi_rows']

# %% ../nbs/10_db_mgmt.ipynb 3
from kedro.config import OmegaConfigLoader
from kedro.framework.project import settings
from pathlib import Path

import pandas as pd
import numpy as np
from tqdm import tqdm

import psycopg2

# %% ../nbs/10_db_mgmt.ipynb 4
def get_db_credentials():
    """
    Fetch PostgreSQL database credentials from the configuration file of the kedro project.

    Uses `OmegaConfigLoader` to load credentials stored under `credentials.postgres`.

    Returns:
        dict: A dictionary with the database connection details (e.g., host, port, user, password, dbname).
    """

    conf_path = str(Path(settings.CONF_SOURCE))
    conf_loader = OmegaConfigLoader(conf_source=conf_path)
    db_credentials = conf_loader["credentials"]["postgres"]

    return db_credentials

# %% ../nbs/10_db_mgmt.ipynb 5
def insert_multi_rows(
    data_to_insert: pd.DataFrame,
    table_name: str,
    column_names: list,
    types: list,
    cur,
    conn,
    return_with_ids: bool = False,
    unique_columns: list = None,  # mandatory if return_with_ids is True
) -> pd.DataFrame | None:
    """
    Inserts data into the specified database table, with an optional return of database-assigned IDs.

    Args:
        data_to_insert (pd.DataFrame): DataFrame containing the data to be inserted.
        table_name (str): Name of the target database table.
        column_names (list): List of column names for the target table.
        types (list): List of Python types (e.g., [int, float]) for data conversion.
        cur (psycopg2.cursor): Database cursor for executing SQL commands.
        conn (psycopg2.connection): Database connection for committing transactions.
        return_with_ids (bool): If True, returns the original DataFrame with an additional "ID" column.

    Returns:
        pd.DataFrame | None: Original DataFrame with an "ID" column if `return_with_ids` is True; otherwise, None.
    """
    logger.info("-- in insert multi rows -- checking data")

    # Check for NaN values and log a warning if any are found
    if data_to_insert.isnull().values.any():
        logger.warning("There are NaNs in the data")

    # Ensure the DataFrame has the correct number of columns
    if len(column_names) != data_to_insert.shape[1]:
        raise ValueError(
            "Number of column names does not match the number of columns in the DataFrame."
        )
    if len(types) != data_to_insert.shape[1]:
        raise ValueError(
            "Number of types does not match the number of columns in the DataFrame."
        )

    logger.info("-- in insert multi rows -- converting data to list of tuples")
    # Convert to list of tuples and apply type casting

    data_values = data_to_insert.values.tolist()
    data_values = [
        tuple(typ(val) for typ, val in zip(types, row)) for row in data_values
    ]

    logger.info("-- in insert multi rows -- preparing SQL")
    # Create SQL placeholders and query
    placeholders = ", ".join(["%s"] * len(column_names))
    column_names_str = ", ".join(f'"{col}"' for col in column_names)

    batch_size_for_commit = (
        1_000_000  # Adjust this based on your dataset size and transaction tolerance
    )
    row_count = 0

    if return_with_ids:
        if not unique_columns:
            raise ValueError(
                "unique_columns must be provided when return_with_ids is True"
            )

        unique_columns_str = ", ".join(f'"{col}"' for col in unique_columns)
        insert_query = f"""
            INSERT INTO {table_name} ({column_names_str})
            VALUES ({placeholders})
            ON CONFLICT ({unique_columns_str})
            DO UPDATE SET "{unique_columns[0]}" = EXCLUDED."{unique_columns[0]}"
            RETURNING "ID";
        """
        ids = []

        # Insert row by row and collect IDs
        with tqdm(total=len(data_values), desc="Inserting rows") as pbar:
            for row in data_values:
                cur.execute(insert_query, row)
                row_id = cur.fetchone()
                if row_id:
                    ids.append(row_id[0])
                row_count += 1
                pbar.update(1)  # Update progress bar for each row

                # Commit every batch_size_for_commit rows
                if row_count % batch_size_for_commit == 0:
                    conn.commit()  # Commit the transaction
        conn.commit()

        # Add IDs back to the original DataFrame
        data_with_ids = data_to_insert.copy()
        data_with_ids["ID"] = ids
        return data_with_ids

    else:
        insert_query = f"""
            INSERT INTO {table_name} ({column_names_str})
            VALUES ({placeholders})
            ON CONFLICT DO NOTHING;
        """

        # Insert row by row without returning IDs
        with tqdm(total=len(data_values), desc="Inserting rows") as pbar:
            for row in data_values:
                cur.execute(insert_query, row)
                row_count += 1
                pbar.update(1)  # Update progress bar for each row
                if row_count % batch_size_for_commit == 0:
                    conn.commit()  # Commit the transaction

        conn.commit()  # Commit all changes after processing

    return None


# %% ../nbs/10_db_mgmt.ipynb 6
from tqdm import tqdm
import psycopg2
from psycopg2.extras import execute_values

class SQLDatabase:
    def __init__(self, autocommit=True):
        self._credentials = get_db_credentials()["con"]
        self.connection = None
        self.autocommit = autocommit

    def connect(self):
        if not self.connection:
            self.connection = psycopg2.connect(self._credentials)
            self.connection.autocommit = self.autocommit

    def close(self):
        if self.connection:
            self.connection.close()
            self.connection = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.connection.rollback()
        elif not self.autocommit:
            self.connection.commit()
        self.close()

    def execute_query(self, query: str, params: tuple = None, fetchall: bool = False, fetchone: bool = False, commit: bool = False):
        if fetchall and fetchone:
            raise ValueError("Both fetchall and fetchone cannot be True")
        if not self.connection:
            self.connect()
        with self.connection.cursor() as cur:
            cur.execute(query, params)
            result = cur.fetchall() if fetchall else cur.fetchone() if fetchone else None
        if commit and self.autocommit:
            self.connection.commit()
        return result

    def execute_multiple_queries(self, queries: list | str, params: list = None, fetchrows: bool = False, commit: bool = False):
        if not self.connection:
            self.connect()
        results = []
        with self.connection.cursor() as cur:
            if fetchrows:
                if isinstance(queries, str):
                    queries = [queries] * len(params)
                for query, par in tqdm(zip(queries, params), total=len(params), desc="Executing queries"):
                    cur.execute(query, par)
                    results.append(cur.fetchone())
            else:
                if not isinstance(queries, str):
                    raise ValueError("For batch execution use a single query with multiple params (set fetchrows=True otherwise)")
                cur.executemany(queries, tqdm(params, desc="Executing batch queries"))
        if commit and self.autocommit:
            self.connection.commit()
        return results if fetchrows else None

    def fetch_ids_bulk(self, table_name: str, id_column, column_names: list, rows: list[tuple]) -> list:
        """
        Retrieve IDs in one bulk query using the VALUES construct.
        'id_column' can be a string or a list/tuple of column names.
        """
        if not rows:
            return []
        columns_str = ", ".join(column_names)
        join_clause = " AND ".join([f"t.{col} = v.{col}" for col in column_names])
        
        # Build the SELECT part based on whether id_column is a single column or multiple.
        if isinstance(id_column, (list, tuple)):
            id_columns_str = ", ".join([f"t.{col}" for col in id_column])
        else:
            id_columns_str = f"t.{id_column}"
            
        query = f"""
            SELECT {id_columns_str}
            FROM {table_name} t
            JOIN (
                VALUES %s
            ) AS v({columns_str})
            ON {join_clause}
        """
        all_ids = []
        chunk_size = 100
        if not self.connection:
            self.connect()
        with self.connection.cursor() as cur:
            for i in tqdm(range(0, len(rows), chunk_size), desc="Fetching IDs", unit="chunk"):
                chunk = rows[i:i + chunk_size]
                execute_values(cur, query, chunk, page_size=len(chunk))
                results = cur.fetchall()
                if isinstance(id_column, (list, tuple)):
                    # Each row is a tuple of id values; convert each value to int.
                    for row in results:
                        all_ids.append(tuple(int(x) for x in row))
                else:
                    all_ids.extend(int(row[0]) for row in results)
        return all_ids

