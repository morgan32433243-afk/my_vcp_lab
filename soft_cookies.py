
def calculate_ingredients(num_cookies):
    """
    根據想製作的餅乾數量，計算所需食材的克數。
    基礎配方設定為製作 12 片餅乾的量。

    基礎配方（約 12 片美式軟餅乾）：
    - 麵粉 (Flour): 150 克
    - 奶油 (Butter): 113 克
    - 糖 (Sugar): 150 克 (通常是兩種糖混合，這裡簡化為總糖量)
    - 巧克力豆 (Chocolate Chips): 170 克
    """

    base_batch_size = 12 # 基礎配方可製作的餅乾數量

    # 基礎配方的食材量 (克)
    base_ingredients = {
        "麵粉": 150,
        "奶油": 113,
        "糖": 150,
        "巧克力豆": 170
    }

    if num_cookies <= 0:
        print("餅乾數量必須是正數。")
        return

    # 計算比例因子
    scaling_factor = num_cookies / base_batch_size

    # 計算所需食材量
    required_ingredients = {
        item: amount * scaling_factor
        for item, amount in base_ingredients.items()
    }

    print(f"\n製作 {num_cookies} 片軟餅乾所需的食材量：")
    for item, amount in required_ingredients.items():
        print(f"- {item}: {amount:.2f} 克")

if __name__ == "__main__":
    try:
        cookies_input = input("請輸入您想製作的餅乾數量：")
        num_cookies = int(cookies_input)
        calculate_ingredients(num_cookies)
    except ValueError:
        print("輸入無效。請輸入一個整數作為餅乾數量。")
    except Exception as e:
        print(f"發生錯誤：{e}")
