-- Create database if not exists
CREATE DATABASE IF NOT EXISTS federal_register;

-- Use the database
USE federal_register;

-- Federal Register database schema

-- Create documents table if it doesn't exist
CREATE TABLE IF NOT EXISTS documents (
    id INT AUTO_INCREMENT PRIMARY KEY,
    document_number VARCHAR(50) UNIQUE NOT NULL,
    title TEXT NOT NULL,
    publication_date DATE,
    document_type VARCHAR(50),
    abstract TEXT,
    html_url VARCHAR(255),
    pdf_url VARCHAR(255),
    type VARCHAR(100),
    subtype VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FULLTEXT(title, abstract)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Create pipeline_runs table to track data updates
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    run_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    start_date DATE,
    end_date DATE,
    documents_added INT DEFAULT 0,
    documents_updated INT DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Create chat_history table to log user interactions
CREATE TABLE IF NOT EXISTS chat_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(50) NOT NULL,
    query TEXT NOT NULL,
    response TEXT NOT NULL,
    tools_used JSON,
    query_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX(session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Create vector_embeddings table for semantic search capability
CREATE TABLE IF NOT EXISTS vector_embeddings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    document_id INT NOT NULL,
    chunk_index INT NOT NULL DEFAULT 0,
    chunk_text TEXT NOT NULL,
    embedding_vector JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
    INDEX(document_id, chunk_index)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Create vector_search procedure for similarity search
-- This is a placeholder - in production it would use an approximation algorithm
DELIMITER //
CREATE PROCEDURE IF NOT EXISTS vector_search(IN query_vector JSON, IN limit_count INT)
BEGIN
    -- In a real implementation, this would use a vector similarity algorithm
    -- For this schema file, we'll just return the newest documents as a placeholder
    SELECT d.* FROM documents d
    ORDER BY d.publication_date DESC
    LIMIT limit_count;
END //
DELIMITER ;

-- Optimize MySQL for fulltext search
-- SET GLOBAL innodb_ft_min_token_size = 3;
ANALYZE TABLE documents; 