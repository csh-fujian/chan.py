import akshare as ak
import logging

if __name__ == '__main__':
    df = ak.stock_zh_a_daily(symbol="sh600000", start_date="20250212", end_date="20250312");
    logging.basicConfig(level=logging.INFO)
    logging.info(df.to_string())
    logging.info("Data downloaded successfully.")