"""数据模型 —— 术语 / 单词表 + 复习记录表 (v0.5)"""
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

    # ---- 记忆复习（六档间隔 1/2/4/7/15/30 天，按天对齐） ----
    review_stage = Column(Integer, default=0)                       # 当前档位 0~5
    next_review_at = Column(DateTime, index=True, nullable=True)    # 下次复习日期（存当天 00:00）
    last_reviewed_at = Column(DateTime, nullable=True)              # 上次复习时间
    review_count = Column(Integer, default=0)                       # 累计复习次数
    in_review = Column(Integer, default=1, index=True)               # 1=在复习队列（为将来移出留口）

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ReviewLog(Base):
    """复习打卡记录 —— 每次自评写一条

    消费方：概览接口「今日已复习数」（按天 distinct word_id，防重复复习虚增）、
    词条详情页展示上次复习情况，也为后续学习统计留底。
    """
    __tablename__ = "review_logs"

    id = Column(Integer, primary_key=True, index=True)
    word_id = Column(Integer, index=True, nullable=False)           # 关联 words.id
    reviewed_at = Column(DateTime, default=datetime.now, index=True)
    result = Column(String(16), nullable=False)                     # remember / fuzzy / forget
    stage_before = Column(Integer, default=0)                       # 自评前档位
    stage_after = Column(Integer, default=0)                        # 自评后档位
