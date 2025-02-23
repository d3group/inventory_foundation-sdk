"""Helper functions to orchestrate Kedro pipelines, e.g., connector functions for database-writing functions"""

# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/20_kedro_orchestration.ipynb.

# %% auto 0
__all__ = ['verify_db_write_status']

# %% ../nbs/20_kedro_orchestration.ipynb 3
# | export

# %% ../nbs/20_kedro_orchestration.ipynb 5
def verify_db_write_status(*args: bool) -> bool:
    """
    Consolidates the outputs of all specific functions that write to the database.
    Each input represents whether a specific write operation was successful (True)
    or not (False). The function returns True only if all inputs are True;
    otherwise, it returns False.

    This function can be used as a standalone node in a Kedro pipeline

    Args:
        *args: A variable number of boolean arguments, each indicating the success
               of a specific database write operation.

    Returns:
        bool: True if all operations were successful (all inputs are True),
              otherwise False.
    """
    return all(args)
