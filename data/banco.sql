CREATE DATABASE IF NOT EXISTS chatbot;
USE chatbot;

-- Tabela de respostas
CREATE TABLE IF NOT EXISTS respostas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    texto TEXT NOT NULL,
    texto_normalizado TEXT NOT NULL,
    embedding_resposta LONGTEXT DEFAULT NULL
);

-- Tabela de perguntas
CREATE TABLE IF NOT EXISTS perguntas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    texto VARCHAR(500) NOT NULL,
    texto_normalizado TEXT NOT NULL,
    embedding LONGTEXT DEFAULT NULL,        
    resposta_id INT,
    FOREIGN KEY (resposta_id) REFERENCES respostas(id),
    FULLTEXT (texto_normalizado)
);

ALTER TABLE perguntas ADD COLUMN keywords TEXT DEFAULT NULL;

-- Tabela de memória pessoal
CREATE TABLE IF NOT EXISTS memoria_pessoal (
    id INT AUTO_INCREMENT PRIMARY KEY,
    tipo VARCHAR(50),                  -- lembrete, aniversario, tarefa, evento
    descricao TEXT,
    data_evento DATETIME,
    repetir_anualmente BOOLEAN DEFAULT FALSE,
    prioridade VARCHAR(20),             -- ex: baixa, media, alta
    tags VARCHAR(200),                  -- separado por vírgula
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabela para registrar feedback das buscas automáticas
CREATE TABLE IF NOT EXISTS feedback_busca (
    id INT AUTO_INCREMENT PRIMARY KEY,
    pergunta_id INT NOT NULL,
    resposta_id INT NOT NULL,
    fonte VARCHAR(50) NOT NULL,         -- ex: Wikipedia, arXiv, Reddit…
    aprovado BOOLEAN NOT NULL,          -- s/n
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (pergunta_id) REFERENCES perguntas(id),
    FOREIGN KEY (resposta_id) REFERENCES respostas(id)
);

-- cria tabela para armazenar itens gerados automaticamente e pendentes de revisão manual
CREATE TABLE IF NOT EXISTS pendencias_revisao (
    id INT AUTO_INCREMENT PRIMARY KEY,
    pergunta_texto TEXT NOT NULL,
    resposta_texto LONGTEXT NOT NULL,
    fonte VARCHAR(100) NOT NULL DEFAULT 'wikipedia',
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    aprovado BOOLEAN DEFAULT FALSE,
    meta JSON DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- Verifica se o índice já existe e cria somente se não existir (workaround MySQL)
SELECT COUNT(*) INTO @idx_exists
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = 'chatbot'
  AND TABLE_NAME = 'respostas'
  AND INDEX_NAME = 'idx_resp_texto_norm';

SET @sql = IF(@idx_exists = 0,
              'CREATE INDEX idx_resp_texto_norm ON respostas(texto_normalizado(255))',
              'SELECT "index_already_exists"');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Normalização básica dos textos já existentes
SET SQL_SAFE_UPDATES = 0;

UPDATE respostas
SET texto_normalizado = LOWER(texto)
WHERE texto_normalizado IS NULL OR texto_normalizado = '';

UPDATE perguntas
SET texto_normalizado = LOWER(texto)
WHERE texto_normalizado IS NULL OR texto_normalizado = '';

SET SQL_SAFE_UPDATES = 1;
