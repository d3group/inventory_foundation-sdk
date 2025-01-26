"""Classes and functions for managing access to the databases"""

# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/10_db_mgmt.ipynb.

# %% auto 0
__all__ = ['get_db_credentials', 'insert_multi_rows', 'check_in_scope_entries']

# %% ../nbs/10_db_mgmt.ipynb 3
from kedro.config import OmegaConfigLoader
from kedro.framework.project import settings
from pathlib import Path

import pandas as pd
import numpy as np
from tqdm import tqdm


import psycopg2


# %% ../nbs/10_db_mgmt.ipynb 5
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

# %% ../nbs/10_db_mgmt.ipynb 6
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
    # logger.info("-- in insert multi rows -- checking data")

    # Check for NaN values and log a warning if any are found
    if data_to_insert.isnull().values.any():
        logger.warning("There are NaNs in the data")
    
    # Ensure the DataFrame has the correct number of columns
    if len(column_names) != data_to_insert.shape[1]:
        raise ValueError("Number of column names does not match the number of columns in the DataFrame.")
    if len(types) != data_to_insert.shape[1]:
        raise ValueError("Number of types does not match the number of columns in the DataFrame.")
    
    # logger.info("-- in insert multi rows -- converting data to list of tuples")
    # Convert to list of tuples and apply type casting

    data_values = data_to_insert.values.tolist()
    data_values = [tuple(typ(val) for typ, val in zip(types, row)) for row in data_values]
    
    # logger.info("-- in insert multi rows -- preparing SQL")
    # Create SQL placeholders and query
    placeholders = ", ".join(["%s"] * len(column_names))
    column_names_str = ", ".join(f'"{col}"' for col in column_names)
    

    batch_size_for_commit = 1_000_000  # Adjust this based on your dataset size and transaction tolerance
    row_count = 0

    if return_with_ids:
        if not unique_columns:
            raise ValueError("unique_columns must be provided when return_with_ids is True")

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

# %% ../nbs/10_db_mgmt.ipynb 7
def check_in_scope_entries(
    target_table,
    dataset_column,
    id_column,
    insert_arguments,
    credentials,
    dataset_id,
    logger,
    filter=None,
    further_primary_keys=None,
    further_primary_keys_values=None,
):
    """
    Ensures all entries in the dataset scope have corresponding entries in the target table.
    If an entry is missing, specified insert_arguments are set to zero.

    Args:
        target_table (str): The name of the target table to check and update.
        dataset_column (str): The name of the column identifying the dataset (e.g., "datasetID").
        id_column (str): The name of the column identifying the entries (e.g., "skuID").
        insert_arguments (list): List of columns to be inserted with default zero values if missing.
        further_primary_keys (list): Additional primary key columns in the target table.
        further_primary_keys_values (list): Corresponding values for further_primary_keys.
    """

    # Check if one is provided without the other
    if (further_primary_keys is None) != (further_primary_keys_values is None):
        raise ValueError("Both further_primary_keys and further_primary_keys_values must be provided together.")

    try:
        with psycopg2.connect(credentials) as conn:
            with conn.cursor() as cur:
                # Step 1: Get all `skuIDs` in the dataset scope
                cur.execute(f"""
                    SELECT "{id_column}"
                    FROM dataset_matching
                    WHERE "{dataset_column}" = %s;
                """, (dataset_id,))
                all_sku_ids = {row[0] for row in cur.fetchall()}

                # Step 2: Build query for `skuIDs` in the target table
                where_clause = f'"{dataset_column}" = %s'
                query_params = [dataset_id]

                if further_primary_keys:
                    additional_conditions = " AND ".join(
                        f'"{key}" = %s' for key in further_primary_keys
                    )
                    where_clause += f" AND {additional_conditions}"
                    query_params.extend(further_primary_keys_values)

                cur.execute(f"""
                    SELECT DISTINCT "{id_column}"
                    FROM {target_table}
                    WHERE {where_clause};
                """, query_params)
                existing_sku_ids = {row[0] for row in cur.fetchall()}

                # Step 3: Identify missing `skuIDs`
                missing_sku_ids = all_sku_ids - existing_sku_ids

                if missing_sku_ids:
                    logger.info(f"Adding missing IDs for {target_table}: {missing_sku_ids}")

                    # Build column list and placeholders
                    columns = [id_column, dataset_column] + insert_arguments
                    value_placeholders = ["%s", "%s"] + ["0"] * len(insert_arguments)

                    if further_primary_keys:
                        columns += further_primary_keys
                        value_placeholders += ["%s"] * len(further_primary_keys)

                    column_list = ", ".join(f'"{col}"' for col in columns)
                    placeholder_list = ", ".join(value_placeholders)

                    for sku_id in missing_sku_ids:
                        # Build arguments dynamically
                        args = [sku_id, dataset_id]
                        if further_primary_keys_values:
                            args += further_primary_keys_values

                        query = f"""
                            INSERT INTO {target_table} ({column_list})
                            VALUES ({placeholder_list})
                            ON CONFLICT ({", ".join(f'"{col}"' for col in [id_column, dataset_column] + (further_primary_keys or []))})
                            DO NOTHING;
                        """

                        # Debugging information
                        # print(f"Executing query: {query}")
                        # print(f"With arguments: {args}")

                        # Execute the query
                        cur.execute(query, args)

                    conn.commit()
                    logger.info(f"Missing IDs handled successfully for {target_table}.")
                else:
                    logger.info("No missing IDs to handle.")
        
    except Exception as e:
        logger.error(f"Error checking in-scope entries for {target_table}: {e}")
        raise e

