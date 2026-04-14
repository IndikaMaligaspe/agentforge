"""
Database connection pool manager.

This module provides a singleton connection pool for database access.
It handles connection pooling, reconnection, and query execution.
"""
import os
import logging
from typing import Any, Dict, List, Optional, Union

import asyncpg

from .observability.logging import get_logger

logger = get_logger(__name__)


class MCPServer:
    """
    Model-Connection-Pool Server for database access.
    
    This class manages a connection pool to the database and provides
    methods for executing queries. It's implemented as a singleton
    to ensure a single connection pool is shared across the application.
    """
    _instance = None
    _pool = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MCPServer, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    async def initialize(self):
        """Initialize the connection pool if not already initialized."""
        if self._initialized:
            return
        
        connection_string = os.getenv("DATABASE_URL")
        if not connection_string:
            logger.error(f"Environment variable DATABASE_URL not set")
            raise ValueError(f"Environment variable DATABASE_URL not set")
        
        try:
            self._pool = await asyncpg.create_pool(
                connection_string,
                min_size=1,
                max_size=10,
            )
            
            logger.info(f"Database connection pool initialized (postgres)")
            self._initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize database connection pool: {str(e)}")
            raise
    
    async def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Execute a SQL query and return the results.
        
        Args:
            query: SQL query to execute
            params: Query parameters (optional)
            
        Returns:
            List of dictionaries representing the query results
        """
        if not self._initialized:
            await self.initialize()
        
        if params is None:
            params = {}
        
        try:
            async with self._pool.acquire() as conn:
                result = await conn.fetch(query, *params.values())
                return [dict(row) for row in result]
        except Exception as e:
            logger.error(f"Query execution failed: {str(e)}")
            logger.error(f"Query: {query}")
            logger.error(f"Params: {params}")
            raise
    
    async def close(self):
        """Close the connection pool."""
        if self._initialized and self._pool:
            await self._pool.close()
            self._initialized = False
            logger.info("Database connection pool closed")


# Singleton instance
mcp_server = MCPServer()


async def execute_sql(query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Execute a SQL query and return the results.
    
    This is a convenience function that uses the MCPServer singleton.
    
    Args:
        query: SQL query to execute
        params: Query parameters (optional)
        
    Returns:
        List of dictionaries representing the query results
    """
    return await mcp_server.execute_query(query, params)