"""数据模型 —— 术语 / 单词表 (v0.4)"""
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from datetime import datetime
from .database import Base


class Word(Base):
    """术语 / 单词表

    核心设计：区分「缩写/全称」、「我的理解 vs 通用释义」、「英美双音标」。
    """
    __tablename__ = "words"

    id = Column(Integer, primary_key=True, index=True)

    # ---- 词形 ----
    abbreviation = Column(String(120), nullable=False, index=True)  # 缩写或主词，如 RAG / token
    full_name = Column(Text, default="")                            # 全称，如 Retrieval-Augmented Generation
    cn_term = Column(String(120), default="")                       # 中文定名，如 词元 / 检索增强
    phonetic_uk = Column(String(120), default="")                   # 英式音标，如 /ˈtəʊ.kən/
    phonetic_us = Column(String(120), default="")                   # 美式音标，如 /ˈtoʊ.kən/

    # ---- 释义 ----
    my_meaning = Column(Text, nullable=False)                       # ⭐ 自己标注的意思（必填）
    domain_detail = Column(Text, default="")                        # 大模型生成的领域详解（长段）
    api_meaning = Column(Text, default="")                          # API 返回的通用释义
    examples = Column(JSON, default=list)                           # 例句，JSON 数组 [{en, zh}]

    # ---- 其他 ----
    tags = Column(Text, default="")                                 # 标签，逗号分隔，如 "大模型,RAG"
    note = Column(Text, default="")                                 # 个人备注
    has_abbr = Column(Integer, default=0)                           # 1=缩写术语 0=普通单词（由 full_name 推导）

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
