"""
Библиотека рекомендательных систем Лаборатории по искусственному интеллекту.
"""
import logging
from typing import Dict, Optional

from pyspark.ml.feature import StringIndexer, StringIndexerModel
from pyspark.ml.recommendation import ALS
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.functions import col, lit
from pyspark.sql.types import DoubleType

from sponge_bob_magic.constants import DEFAULT_CONTEXT
from sponge_bob_magic.models.base_recommender import Recommender
from sponge_bob_magic.utils import get_top_k_recs


class ALSRecommender(Recommender):
    """ Обёртка вокруг реализации ALS на Spark. """

    _seed: Optional[int] = None
    user_indexer_model: StringIndexerModel
    item_indexer_model: StringIndexerModel

    """ Обёртка вокруг ALS на Spark. """
    def __init__(self, spark: SparkSession,
                 rank: int = 10):
        """
        Инициализирует параметры модели и сохраняет спарк-сессию.

        :param spark: инициализированная спарк-сессия
        :param rank: матрицей какого ранга приближаем исходную
        """
        super().__init__(spark)
        self.rank = rank
        self.user_indexer = StringIndexer(inputCol="user_id",
                                          outputCol="user_idx")
        self.item_indexer = StringIndexer(inputCol="item_id",
                                          outputCol="item_idx")

    def get_params(self) -> Dict[str, object]:
        return {
            "rank": self.rank
        }

    def _pre_fit(self, log: DataFrame,
                 user_features: Optional[DataFrame],
                 item_features: Optional[DataFrame]) -> None:
        self.user_indexer_model = self.user_indexer.fit(log)
        self.item_indexer_model = self.item_indexer.fit(log)

    def _fit_partial(self, log: DataFrame, user_features: Optional[DataFrame],
                     item_features: Optional[DataFrame]) -> None:
        logging.debug("Индексирование данных")
        log_indexed = self.user_indexer_model.transform(log)
        log_indexed = self.item_indexer_model.transform(log_indexed)

        logging.debug("Обучение модели")
        self.model = ALS(
            rank=self.rank,
            userCol="user_idx",
            itemCol="item_idx",
            ratingCol="relevance",
            implicitPrefs=True,
            seed=self._seed
        ).fit(log_indexed)

    def _predict(self,
                 k: int,
                 users: DataFrame, items: DataFrame,
                 context: str, log: DataFrame,
                 user_features: Optional[DataFrame],
                 item_features: Optional[DataFrame],
                 to_filter_seen_items: bool = True) -> DataFrame:
        test_data = users.crossJoin(items).withColumn("relevance", lit(1))

        if to_filter_seen_items:
            test_data = self._filter_seen_recs(
                test_data,
                log
            ).drop("relevance")

        log_indexed = self.user_indexer_model.transform(test_data)
        log_indexed = self.item_indexer_model.transform(log_indexed)

        recs = (
            self.model.transform(log_indexed)
            .withColumn("relevance", col("prediction").cast(DoubleType()))
            .drop("user_idx", "item_idx", "prediction")
            .cache()
        )
        recs = get_top_k_recs(recs, k).withColumn(
            "context", lit(DEFAULT_CONTEXT)
        )

        return recs