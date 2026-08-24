#!/usr/bin/env python3
"""
FastFest Automated Microsoft SQL Server (SSMS) Database Creator
==============================================================
Connects to SQL Server (local or remote) using pyodbc with
Windows Authentication or SQL Authentication and automatically creates
the 'fastfest' database if it does not exist.

Usage:
  python create_mssql_db.py [--server localhost] [--dbname fastfest]
  python create_mssql_db.py --server localhost --user sa --password YOUR_PASSWORD
"""

import os
import sys
import argparse
from dotenv import load_dotenv
import pyodbc

load_dotenv('.env')

def create_database(server="localhost", dbname="fastfest", user=None, password=None, driver="ODBC Driver 18 for SQL Server"):
    print(f"Connecting to Microsoft SQL Server at '{server}'...")
    
    if user and password:
        conn_str = (
            f"Driver={{{driver}}};"
            f"Server={server};"
            f"Database=master;"
            f"UID={user};"
            f"PWD={password};"
            f"TrustServerCertificate=yes;"
        )
    else:
        # Windows Authentication (Default for SSMS on local machine)
        conn_str = (
            f"Driver={{{driver}}};"
            f"Server={server};"
            f"Database=master;"
            f"Trusted_Connection=yes;"
            f"TrustServerCertificate=yes;"
        )
        
    try:
        conn = pyodbc.connect(conn_str, autocommit=True)
        cur = conn.cursor()
        
        # Check if database already exists
        cur.execute("SELECT database_id FROM sys.databases WHERE name = ?", (dbname,))
        exists = cur.fetchone()
        
        if not exists:
            cur.execute(f"CREATE DATABASE [{dbname}];")
            print(f"[+] Database '[{dbname}]' created successfully on SQL Server!")
        else:
            print(f"[*] Database '[{dbname}]' already exists on SQL Server.")
            
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[!] Failed to connect or create database on SQL Server: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Create FastFest Microsoft SQL Server (SSMS) Database")
    parser.add_argument("--server", default="localhost", help="SQL Server instance (default: localhost)")
    parser.add_argument("--dbname", default="fastfest", help="Database name to create (default: fastfest)")
    parser.add_argument("--user", default=None, help="SQL Server username (optional, defaults to Windows Auth)")
    parser.add_argument("--password", default=None, help="SQL Server password (optional)")
    parser.add_argument("--driver", default="ODBC Driver 18 for SQL Server", help="ODBC Driver name")
    
    args = parser.parse_args()
    success = create_database(args.server, args.dbname, args.user, args.password, args.driver)
    
    if success:
        print("\n[+] Ready! You can now run:")
        print("   python migrate_sqlite_to_mssql.py")
        print("   python app.py\n")


if __name__ == "__main__":
    main()
