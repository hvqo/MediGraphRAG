"""Historical experiment recovered from docx/process/data/dataProcess.ipynb.

Source preserved for reference, not the supported application pipeline.
Imports are safe: no model calls or data writes occur on import.
Use python -m backend.app.cli for maintained offline operations.
"""

def historical_pipeline():
    # source-cell:2
    from langchain_community.llms import Ollama
    from langchain_core.output_parsers import JsonOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    import os
    from docx import Document
    import json
    from tqdm import tqdm  

    import pandas as pd

    import warnings
    warnings.filterwarnings("ignore")

    # source-cell:3
    def read_docx(file_path):
        doc = Document(file_path)
        text = []
        for paragraph in doc.paragraphs:
            text.append(paragraph.text)
        return '\n'.join(text)

    folder_path = '/home/lin/work/code/DeepLearning/LLM/file/医疗语料/西医综合/'
    all_content = []

    # 获取所有 .docx 文件的列表
    docx_files = [filename for filename in os.listdir(folder_path) if filename.endswith('.docx')]

    # 使用 tqdm 添加进度条
    for filename in tqdm(docx_files, desc='Processing files'):
        file_path = os.path.join(folder_path, filename)
        content = read_docx(file_path)
        content = content.split('\n\n')
        all_content.extend(content)

    content = all_content
    print(content)

    # source-cell:4
    systemContent = r"""你是我的医学文件整理助理，我有题目要你帮我整理

    要求如下：
    - 我发给你的题目包含题目、答案、解析
    - 你需要返回一个这一个题目的详细知识点
    - 我发给你的不一定的可以会出错，会发给你空字符串或者非试题，有或者试题没有答案或解析，这个时候你返回空给我即可
    - 你不需要返回题目相关信息给我，比如选项
    - 只需要返回指定内容，不需要其他内容
    - 确保输出是紧凑格式的有效JSON格式，不包含任何其他解释、转义符、换行符或反斜杠

    输出案例：
    {{'knowledge':'肺结节是指在胸部影像学检查（如CT或X光）中发现的小于3厘米的局部肿块，可以是良性（如肉芽肿或感染后的瘢痕）或恶性（如肺癌）。诊断时，需要综合考虑结节的影像学特征，如边缘是否光滑、是否有钙化以及形状和密度等。此外，医生通常会根据患者的吸烟史、年龄、家族史等风险因素来判断结节的性质。随访观察非常重要，定期复查CT影像可以帮助监测结节是否增长，从而指导后续的治疗方案。对于疑似恶性的结节，可能需要进行病理学检查，如穿刺活检，以获得确诊。'}}

    """


    prompt_template = ChatPromptTemplate.from_messages(
        [("system", systemContent), ("user", "{text}")]
    )

    model = Ollama(model="qwen2.5",temperature=0.0)
    parser = JsonOutputParser()
    chain =  prompt_template | model | parser

    # source-cell:5
    if not os.path.exists('../../data/knowledge/knowledge.json'):
        with open('../../data/knowledge/knowledge.json', 'w') as f:
            json.dump([], f)

    # 读取现有数据
    with open('../../data/knowledge/knowledge.json', 'r') as f:
        responses = json.load(f)

    for i in tqdm(content):
        time = 0
        while True:
            try:      
                response = chain.invoke({"text": i})
                if isinstance(response, dict):
                    if response:
                        responses.append(response)  # 添加响应
                        # 立即写入文件
                        with open('../../data/knowledge/knowledge.json', 'w') as f:
                            json.dump(responses, f, ensure_ascii=False, indent=4)
                        break
                    else:
                        break
            except:
                time+=1
                if time>5:
                    break
                pass

    # source-cell:7
    data = pd.read_json('../../data//knowledge/knowledge.json')
    data = data.drop_duplicates(keep='last',ignore_index=True)
    data

    # source-cell:8
    systemContent = r"""任务：  
    从给定的文本中自动抽取出实体

    模型参与的角色：  
    你将作为一个医学知识图谱的构建助手，负责从医学文本中识别和提取重要实体，并将提取结果以结构化的形式呈现。

    要求：
    1. 识别出文本中的主要实体，并对实体分类。
    2. 确保输出是紧凑格式的有效JSON格式，不包含任何其他解释、转义符、换行符或反斜杠
    3. 注意只需要提取与医疗相关实体，不需要提取太过于泛的实体，比如`人群`，要求如下：

    - 实体字段
    疾病（Disease）：疾病名称、疾病编码（如ICD-10）、描述、分类（如慢性病、传染病等）。
    药物（Drug）：药物名称、剂量、适应症、禁忌、常见副作用。
    症状（Symptom）：症状名称、描述、严重程度、出现频率。
    治疗方法（Treatment）：治疗方案、方法（如手术、药物治疗）、疗效、适应症。
    检查项目（Test）：检查名称、目的、结果范围、相关疾病。

    4. 最终输出应包含一个包含多个实体的dict。

    输出案例：  
    给定文本：  
    "胰岛素是调节血糖水平的重要激素，胰腺是其主要分泌腺体。"

    **系统应输出以下字典格式：**
    {{
      "knowledge": "胰岛素是调节血糖水平的重要激素，胰腺是其主要分泌腺体。",
      "entities": [
        {{
          "entity": "胰岛素",
          "type": "激素",
          "description": "调节血糖水平的激素"
        }},
        {{
          "entity": "血糖水平",
          "type": "生理指标",
          "description": "血液中的葡萄糖含量"
        }},
        {{
          "entity": "胰腺",
          "type": "器官",
          "description": "分泌胰岛素的腺体"
        }}
      ]
    }}

    """

    prompt_template = ChatPromptTemplate.from_messages(
        [("system", systemContent), ("user", "{text}")]
    )

    model = Ollama(model="qwen2.5",temperature=0.0)
    parser = JsonOutputParser()
    chain =  prompt_template | model | parser

    # source-cell:9
    summaryContent = r"""任务： 从给定的文本中自动抽取出实体及其相互关系，构建知识图谱，并将提取结果以结构化的形式呈现

    要求：
    1. `relation`中的实体，应仅从提供的实体中提取。
    2. 从文本中提取实体之间的关系，明确并准确描述关系类型。
    3. 输出应采用字典格式，实体和关系以 `dict` 表示，关系以三元组形式。
    4. 确保输出是紧凑格式的有效JSON格式，不包含任何其他解释、转义符、换行符或反斜杠
    5. 注意只需要提取与医疗相关的实体关系，要求如下：

    - 关系字段
    疾病与症状：哪些症状与哪些疾病相关联（例如，咳嗽与肺炎）。
    疾病与药物：哪些药物用于治疗特定疾病（例如，阿莫西林用于治疗细菌感染）。
    症状与检查项目：某些症状需要进行哪些检查（例如，咳嗽需要进行胸部X光）。
    药物与副作用：药物可能引起的副作用（例如，阿司匹林可能导致胃肠不适）。

    关系应当包括但不限于以下：["导致症状", "伴随症状", "治疗方法", "疗效", "风险因素", "保护因素", "检查方法", "检查指标", "高发人群", "易感人群", "药物治疗", "药物副作用", "病理表现", "生物标志物", "发生率", "预后因素", "病因", "传播途径", "预防措施", "生活方式影响", "相关疾病", "诊断标准", "自然病程", "临床表现", "并发症", "危险信号", "遗传因素", "环境因素", "生活方式干预", "治疗费用", "治疗反应", "康复措施", "心理影响", "社会影响"]


    6. 最终输出应包含一个包含多个关系的列表，以便用于知识图谱构建。

    输出案例：  

    **系统应输出以下字典格式：**

    {{
      "knowledge": "胰岛素是调节血糖水平的重要激素，胰腺是其主要分泌腺体。",
      "entities": [
        {{
          "entity": "胰岛素",
          "type": "激素",
          "description": "调节血糖水平的激素"
        }},
        {{
          "entity": "血糖水平",
          "type": "生理指标",
          "description": "血液中的葡萄糖含量"
        }},
        {{
          "entity": "胰腺",
          "type": "器官",
          "description": "分泌胰岛素的腺体"
        }}
      ],
      "relation": [
        {{
          "entity1": "胰岛素",
          "relation": "调节",
          "entity2": "血糖水平"
        }},
        {{
          "entity1": "胰岛素",
          "relation": "主要分泌腺体",
          "entity2": "胰腺"
        }}
      ]
    }}

    """

    summary_template = ChatPromptTemplate.from_messages(
        [("system", summaryContent), ("user", "{text}")]
    )

    summarymodel = Ollama(model="qwen2.5",temperature=0.0)
    summarychain =  summary_template | summarymodel | parser

    # source-cell:10
    if not os.path.exists('../../data/graph/graph.json'):
        with open('../../data/graph/graph.json', 'w') as f:
            json.dump([], f)

    # 读取现有数据
    with open('../../data/graph/graph.json', 'r') as f:
        responses = json.load(f)

    for i in tqdm(data['knowledge']):
        time = 0
        while True:
            try:      
                entitys = chain.invoke({"text": i})
                response = summarychain.invoke({"text": entitys})
                if isinstance(response, dict):
                    if response:
                        responses.append(response)  # 添加响应
                        # 立即写入文件
                        with open('../../data/graph/graph.json', 'w') as f:
                            json.dump(responses, f, ensure_ascii=False, indent=4)
                        break
                    else:
                        break
            except:
                time+=1
                if time>5:
                    break
                pass

    # source-cell:12
    from langchain_community.llms import Ollama
    from langchain_core.output_parsers import JsonOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    import os
    from docx import Document
    import json
    from tqdm import tqdm  

    import pandas as pd

    import warnings
    warnings.filterwarnings("ignore")

    # source-cell:13
    def revise_format(json_data):
        if "relations" in json_data and isinstance(json_data["relations"], str):
            json_data["relation"] = json_data.pop("relations")

        if "entitie" in json_data and isinstance(json_data["entitie"], str):
            json_data["entities"] = json_data.pop("entitie")

        # 检查 "knowledge" 字段
        if "knowledge" not in json_data or not isinstance(json_data["knowledge"], str):
            json_data['knowledge'] = ''

        # 检查 "entities" 字段
        if "entities" not in json_data or not isinstance(json_data["entities"], list):
            json_data['entities'] = []
        
        else:
            for index, entity in enumerate(json_data["entities"]):
                missing_keys = [key for key in ["entity", "type", "description"] if key not in entity]
                if missing_keys:
                    for rel in json_data['entities']:
                        if '描述' in rel:
                            rel['description'] = rel.pop('描述')
            
        # 检查 "relation" 字段
        if "relation" not in json_data or not isinstance(json_data["relation"], list):
            json_data['relation'] = []
        else:
            for index, relation in enumerate(json_data["relation"]):
                missing_keys = [key for key in ["entity1", "relation", "entity2"] if key not in relation]
                if missing_keys:
                    for rel in json_data['relation']:
                        if 'subject' in rel:
                            rel['entity1'] = rel.pop('subject')
                        if 'predicate' in rel:
                            rel['relation'] = rel.pop('predicate')
                        if 'object' in rel:
                            rel['entity2'] = rel.pop('object')
                        if 'type' in rel:
                            rel['relation'] = rel.pop('type')
                        if 'relationship' in rel:
                            rel['relation'] = rel.pop('relationship')
        
        return json_data

    def check_json_file(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if not isinstance(data, list):
                print(f"File '{file_path}' is not a valid list of JSON objects.")
                return

            # 验证每个 JSON 对象的格式
            for idx, json_object in enumerate(data):
                data[idx] = revise_format(json_object)

        except json.JSONDecodeError as e:
            print(f"JSON Decode Error: {e}")
        except Exception as e:
            print(f"An error occurred: {e}")

        return data
    
    # 文件路径
    json_file_path = "../../data/graph/graph.json"

    # 检查 JSON 文件
    data = check_json_file(json_file_path)                

    # source-cell:14
    def validate_json_format(json_data):
        errors = []

        # 检查 "knowledge" 字段
        if "knowledge" not in json_data or not isinstance(json_data["knowledge"], str):
            errors.append(("knowledge", "Missing or invalid 'knowledge' field"))

        # 检查 "entities" 字段
        if "entities" not in json_data or not isinstance(json_data["entities"], list):
            errors.append(("entities", "Missing or invalid 'entities' field"))
        else:
            for index, entity in enumerate(json_data["entities"]):
                missing_keys = [key for key in ["entity", "type", "description"] if key not in entity]
                if missing_keys:
                    errors.append((f"entities[{index}]", f"Missing keys: {', '.join(missing_keys)}"))

        # 检查 "relation" 字段
        if "relation" not in json_data or not isinstance(json_data["relation"], list):
            errors.append(("relation", "Missing or invalid 'relation' field"))
        else:
            for index, relation in enumerate(json_data["relation"]):
                missing_keys = [key for key in ["entity1", "relation", "entity2"] if key not in relation]
                if missing_keys:
                    errors.append((f"relation[{index}]", f"Missing keys: {', '.join(missing_keys)}"))

        return errors

    # source-cell:15
    systemContent = r"""任务：  
    从给定的文本中自动抽取出实体

    模型参与的角色：  
    你将作为一个医学知识图谱的构建助手，负责进行我的实体的命名的修改。

    要求：
    1. 识别出dict中的主要实体，对命名错误的进行修正
    2. 确保输出是紧凑格式的有效JSON格式，不包含任何其他解释、转义符、换行符或反斜杠
    3. 最终输出应包含一个包含多个实体的dict。

    **系统应输出以下字典格式：**
    {{
      "knowledge": "胰岛素是调节血糖水平的重要激素，胰腺是其主要分泌腺体。",
      "entities": [
        {{
          "entity": "胰岛素",
          "type": "激素",
          "description": "调节血糖水平的激素"
        }},
        {{
          "entity": "血糖水平",
          "type": "生理指标",
          "description": "血液中的葡萄糖含量"
        }},
        {{
          "entity": "胰腺",
          "type": "器官",
          "description": "分泌胰岛素的腺体"
        }}
      ],
      "relation": [
        {{
          "entity1": "胰岛素",
          "relation": "调节",
          "entity2": "血糖水平"
        }},
        {{
          "entity1": "胰岛素",
          "relation": "主要分泌腺体",
          "entity2": "胰腺"
        }}
      ]
    }}

    """

    prompt_template = ChatPromptTemplate.from_messages(
        [("system", systemContent), ("user", "{text}")]
    )

    model = Ollama(model="qwen2.5",temperature=0.0)
    parser = JsonOutputParser()
    chain =  prompt_template | model | parser

    # source-cell:16
    for idx, json_object  in tqdm(enumerate(data)):
        error = validate_json_format(json_object) 
        if error:
            data[idx] = chain.invoke({'text':json_object})

    data = [json_object for json_object in data if not validate_json_format(json_object)]

    # source-cell:17
    for idx, json_object in enumerate(data):
        if validate_json_format(json_object):
            print(f'{idx}: {validate_json_format(json_object)}')

    with open('../../data/graph/graph.json', 'w', encoding='utf-8') as json_file:
        json.dump(data, json_file, ensure_ascii=False, indent=4)

    # source-cell:19
    import warnings
    warnings.filterwarnings("ignore")

    import json
    from tqdm import tqdm
    from neo4j import GraphDatabase

    with open('../../data/graph/graph.json') as file:
        data = json.load(file)

    # source-cell:20
    class Neo4jHandler:
        def __init__(self, uri, user, password):
            self.driver = GraphDatabase.driver(uri, auth=(user, password))
            self.session = self.driver.session()
    
        def close(self):
            self.session.close()
            self.driver.close()
    
        def create_node(self, entity_name, entity_type=None):
            for i in range(3):
                try:
                    if entity_type:
                        query = f"MERGE (n:`{entity_type}` {{name: $name}})"
                    else:
                        query = "MERGE (n {name: $name})"
                    self.session.run(query, name=entity_name)
                    break
                except:
                    time.sleep(2)

        def create_relationship(self, entity1_name, relation_type, entity2_name, properties=None):
            for i in range(3):
                try:
                    if properties:
                        props = ', '.join([f"{key}: ${key}" for key in properties.keys()])
                        query = f"""
                        MATCH (a {{name: $entity1_name}}), (b {{name: $entity2_name}})
                        MERGE (a)-[:`{relation_type}` {{{props}}}]->(b)
                        """
                    else:
                        query = f"""
                        MATCH (a {{name: $entity1_name}}), (b {{name: $entity2_name}})
                        MERGE (a)-[:`{relation_type}`]->(b)
                        """
                    self.session.run(query, entity1_name=entity1_name, entity2_name=entity2_name, **(properties or {}))
                    break
                except:
                    time.sleep(2)

    # source-cell:22
    uri = "bolt://localhost:7687"
    user = "neo4j"
    password = "password"

    neo4j_handler = Neo4jHandler(uri, user, password)

    # source-cell:23
    for d in tqdm(data):
        knowledge = f"{d['knowledge']}"
        entities = d['entities']
        relation = d['relation']
        if knowledge != '':
            neo4j_handler.create_node(entity_name=knowledge, entity_type="knowledge")
        for entitiy in entities:
            entity_name = f"{entitiy['entity']}"
            entity_type = f"{entitiy['type']}"
            description = f"{entitiy['description']}"

            neo4j_handler.create_node(entity_name=entity_name, entity_type='entity')
            neo4j_handler.create_node(entity_name=description, entity_type='description')
            neo4j_handler.create_node(entity_name=entity_type, entity_type='type')
            if entity_name and description:
                neo4j_handler.create_relationship(entity1_name=entity_name, relation_type='description', entity2_name=description)

            if entity_name and entity_type:
                neo4j_handler.create_relationship(entity1_name=entity_name, relation_type='type', entity2_name=entity_type)
        
            if knowledge != '' and entity_name and knowledge:
                neo4j_handler.create_relationship(entity1_name=entity_name, relation_type='knowledge', entity2_name=knowledge)

        for rela in relation:
            if rela['entity1']:
                entity1 = f"{rela['entity1']}"
            if rela['entity2']:
                if isinstance(rela['entity2'], list):
                    entity2 = [f"{item}" for item in rela['entity2']]
                else:
                    entity2 = f"{rela['entity2']}"

            neo4j_handler.create_node(entity_name=entity1, entity_type='entity')
        
            if entity1 and entity2 and rela['relation']:
                if isinstance(rela['entity1'], list):
                    for e1 in rela['entity1']:
                        neo4j_handler.create_node(entity_name=e1, entity_type='entity')
                        if knowledge != '':
                            neo4j_handler.create_relationship(entity1_name=e1, relation_type='knowledge', entity2_name=knowledge)

                        if isinstance(rela['entity2'], list):
                            for e2 in rela['entity2']:
                                neo4j_handler.create_node(entity_name=e2, entity_type='entity')
                                neo4j_handler.create_relationship(entity1_name=e1, relation_type='relation', entity2_name=f"{e2}", properties={'relation': rela['relation']})
                                if knowledge != '':
                                    neo4j_handler.create_relationship(entity1_name=e2, relation_type='knowledge', entity2_name=knowledge)
                        else:
                            neo4j_handler.create_node(entity_name=entity2, entity_type='entity')
                            neo4j_handler.create_relationship(entity1_name=e1, relation_type='relation', entity2_name=entity2, properties={'relation': rela['relation']})
                            if knowledge != '':
                                    neo4j_handler.create_relationship(entity1_name=entity2, relation_type='knowledge', entity2_name=knowledge)
                else:
                    neo4j_handler.create_node(entity_name=entity1, entity_type='entity')               
                    if knowledge != '':
                            neo4j_handler.create_relationship(entity1_name=entity1, relation_type='knowledge', entity2_name=knowledge)
     
                    if isinstance(rela['entity2'], list):
                        for e2 in rela['entity2']:
                            neo4j_handler.create_node(entity_name=e2, entity_type='entity')
                            neo4j_handler.create_relationship(entity1_name=entity1, relation_type='relation', entity2_name=f"{e2}", properties={'relation': rela['relation']})
                            if knowledge != '':
                                neo4j_handler.create_relationship(entity1_name=e2, relation_type='knowledge', entity2_name=knowledge)
                    else:
                        neo4j_handler.create_node(entity_name=entity2, entity_type='entity')
                        neo4j_handler.create_relationship(entity1_name=entity1, relation_type='relation', entity2_name=entity2, properties={'relation': rela['relation']})
                        if knowledge != '':
                                neo4j_handler.create_relationship(entity1_name=entity2, relation_type='knowledge', entity2_name=knowledge)

    neo4j_handler.close()

    # source-cell:24



if __name__ == "__main__":
    print("Historical source archive. Use python -m backend.app.cli --help for supported commands.")
