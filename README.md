# Chatbot IA - Protótipo TCC 2025

## Sobre o Projeto

Este projeto foi o meu primeiro protótipo de Chatbot com Inteligência Artificial, desenvolvido como base de estudo e aplicação prática para o meu TCC de 2025.

Ele foi construído inteiramente por mim, em um momento em que eu ainda tinha pouca compreensão sobre arquitetura de IA e organização de sistemas complexos. Por isso, o projeto representa um marco importante na minha evolução como programador.

O foco principal foi aprendizado contínuo em Python, integração com banco de dados, uso de bibliotecas da Hugging Face e construção de um sistema distribuído utilizando um Raspberry Pi 3 B+.

---

## Objetivo do Protótipo

- Entender como estruturar um chatbot em Python
- Aprender integração com banco de dados MySQL
- Trabalhar com arquitetura cliente-servidor
- Explorar bibliotecas de IA da Hugging Face
- Implementar sistema de TTS (Text-to-Speech)
- Organizar o código em múltiplos módulos
- Criar um sistema funcional sem uso de modelos generativos

---

## Arquitetura do Sistema

O sistema foi dividido em dois ambientes principais:

### 1. Raspberry Pi 3 B+

Responsável por:

- Capturar a entrada do usuário
- Enviar requisições ao servidor principal
- Receber respostas processadas
- Executar o mecanismo de TTS
- Interagir diretamente com o usuário

Funcionava como cliente da aplicação.

---

### 2. Servidor (PC Principal)

Responsável por:

- Receber as mensagens enviadas pelo Raspberry Pi
- Processar a pergunta
- Consultar o banco de dados MySQL
- Buscar respostas correspondentes
- Retornar a resposta adequada ao cliente

Funcionava como núcleo de processamento da IA.

---

## Funcionamento do Chatbot

Este chatbot não era generativo.

Ele funcionava com base em:

- Frases pré-cadastradas no banco de dados
- Perguntas previamente estruturadas
- Busca por similaridade ou correspondência
- Retorno de respostas já armazenadas

O fluxo era:

1. Usuário envia pergunta via Raspberry Pi
2. Cliente envia requisição para o servidor
3. Servidor processa e consulta o banco
4. Sistema identifica a melhor correspondência
5. Resposta é enviada de volta
6. Raspberry executa TTS e fala com o usuário

---

## Tecnologias Utilizadas

- Python 3.10.11
- MySQL
- Raspberry Pi 3 B+
- Bibliotecas da Hugging Face
- Sistema cliente-servidor com client.py e server.py
- Módulos separados para organização do código

---

## Banco de Dados

O banco MySQL armazenava:

- Perguntas cadastradas
- Respostas correspondentes
- Estrutura de frases relacionadas
- Dados auxiliares para busca

A lógica era baseada em correspondência e organização manual de conteúdo.

---

## Mecanismo de TTS

O chatbot possuía sistema de Text-to-Speech utilizando bibliotecas da Hugging Face.

Características:

- Voz personalizada baseada na voz de um amigo
- Resposta falada ao usuário
- Integração com o fluxo principal do sistema

---

## Organização do Código

O projeto foi dividido em múltiplos arquivos e módulos para:

- Separar responsabilidades
- Facilitar manutenção
- Melhorar entendimento do fluxo
- Reduzir complexidade em arquivos únicos

Cada processo possuía seu próprio script, como:

- Processamento
- Banco de dados
- Embeddings
- Memória
- Respostas
- Cliente
- Servidor
- Testes

---

## Limitações do Protótipo

- Não utilizava modelos generativos
- Dependência de frases previamente cadastradas
- Lógica de correspondência ainda simples
- Arquitetura inicial sem grande otimização
- Escalabilidade limitada

Apesar disso, o sistema era funcional e cumpria seu propósito.

---

## Aprendizados

- Estruturação de sistemas distribuídos
- Comunicação cliente-servidor
- Uso prático de MySQL com Python
- Integração com bibliotecas de IA
- Implementação de TTS
- Organização modular de código
- Evolução gradual da lógica de programação

Este projeto marcou o início da minha jornada mais séria com desenvolvimento de IA e consolidou bases importantes para projetos futuros.

---

## Status

Protótipo funcional utilizado como base de estudo e desenvolvimento para o TCC 2025.
