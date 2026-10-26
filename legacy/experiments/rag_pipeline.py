"""Historical experiment recovered from docx/process/rag/ragProcess.ipynb.

Source preserved for reference, not the supported application pipeline.
Imports are safe: no model calls or data writes occur on import.
Use python -m backend.app.cli for maintained offline operations.
"""

def historical_pipeline():
    # source-cell:2
    from neo4j import GraphDatabase

    class Neo4jEntityFetcher:
        def __init__(self, uri, user, password):
            self.driver = GraphDatabase.driver(uri, auth=(user, password))

        # 获取所有实体（节点）
        def get_all_entities(self):
            with self.driver.session() as session:
                query = "MATCH (n) RETURN n"
                result = session.run(query)
                # 将实体的属性存入列表
                entities = [{"id": record["n"].element_id, "labels": list(record["n"].labels), "properties": dict(record["n"])} for record in result]
                return entities

        # 获取指定标签的实体
        def get_entities_by_label(self, label):
            with self.driver.session() as session:
                query = f"MATCH (n:{label}) RETURN n"
                result = session.run(query)
                # 将实体的属性存入列表
                entities = [{"id": record["n"].element_id, "labels": list(record["n"].labels), "properties": dict(record["n"])} for record in result]
                return entities

        # 获取指定属性的实体
        def get_entities_by_property(self, property_name, property_value):
            with self.driver.session() as session:
                query = f"MATCH (n {{{property_name}: '{property_value}'}}) RETURN n"
                result = session.run(query)
                # 将实体的属性存入列表
                entities = [{"id": record["n"].element_id, "labels": list(record["n"].labels), "properties": dict(record["n"])} for record in result]
                return entities
            
        # 根据 ID 获取实体
        def get_entity_by_id(self, element_id):
            with self.driver.session() as session:
                query = "MATCH (n) WHERE elementId(n) = $element_id RETURN n"
                result = session.run(query, element_id=element_id)
                # 获取实体的属性
                entity = [{"id": record["n"].element_id, "labels": list(record["n"].labels), "properties": dict(record["n"])} for record in result]
                return entity


        def get_entities_by_knowledge_id(self, element_id):
            with self.driver.session() as session:
                query = "MATCH (m)-[r]->(n) WHERE elementId(n) = $element_id RETURN m, r"
                result = session.run(query, element_id=element_id)
                entity = [{"id": record["m"].element_id, "labels": list(record["m"].labels), "properties": dict(record["m"])} for record in result]
                return entity

    
        def get_entities_by_entities_id(self, element_id):
            with self.driver.session() as session:
                query = "MATCH (n)-[r]->(m) WHERE elementId(n) = $element_id RETURN n, r, m"
                result = session.run(query, element_id=element_id)
                entity = [
                    {
                        "key": dict(record["n"])['name'],
                        "id": record["m"].element_id[0],
                        "labels": list(record["m"].labels)[0],
                        "properties": dict(record["m"])['name'],
                        "relationship": {
                            "type": record["r"].type,  
                            "properties": dict(record["r"])
                        }
                    } for record in result
                ]
                return entity

    
    
        # 关闭驱动
        def close(self):
            self.driver.close()


    # 初始化 Neo4jEntityFetcher
    uri = "bolt://localhost:7687"  # Neo4j 数据库地址
    user = "neo4j"  # Neo4j 用户名
    password = "password"  # Neo4j 密码
    fetcher = Neo4jEntityFetcher(uri, user, password)

    # 获取所有实体
    # print("所有实体：")
    all_entities = fetcher.get_all_entities()

    # 根据标签获取实体
    # print("\n标签为 'knowledge' 的实体：")
    knowledge_entities = fetcher.get_entities_by_label("knowledge")

    # 根据属性获取实体
    # print("\n具有 name='糖尿病' 属性的实体：")
    diabetes_entities = fetcher.get_entities_by_property("name", "糖尿病")
    
    # 关闭连接
    fetcher.close()

    # source-cell:3
    diabetes_entities

    # source-cell:4
    knowledge_entities[0]

    # source-cell:6
    import warnings
    warnings.filterwarnings("ignore")

    # source-cell:7
    def LoadModel(model_path='../../model/bge-large-zh-v1.5'):
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")  

        model = AutoModel.from_pretrained(model_path).to(device)  
        tokenizer = AutoTokenizer.from_pretrained(model_path)
   
        return model, tokenizer

    # source-cell:8
    def encode_text(model, tokenizer, text, max_length=512):
        device = model.device
        inputs = tokenizer(text, return_tensors='pt', padding=True, truncation=True, max_length=max_length).to(device)

        model.eval()

        with torch.no_grad():
            outputs = model(**inputs)
            embeddings = outputs.last_hidden_state.mean(dim=1).cpu().tolist() 
        return embeddings

    # 使用示例
    text = "输入文本"
    model, tokenizer = LoadModel()
    embeddings = encode_text(model, tokenizer, text)
    print(embeddings)

    # source-cell:10
    from process.rag.Neo4jEntityFetcher import Neo4jEntityFetcher
    from legacy.prototypes.rag.Embedding import (LoadModel, encode_text, warnings, os, pd, tqdm, KeyedVectors, AutoModel, AutoTokenizer, torch, nn)
    import faiss
    import numpy as np

    # source-cell:11
    uri = "bolt://localhost:7687"  # Neo4j 数据库地址
    user = "neo4j"  # Neo4j 用户名
    password = "password"  # Neo4j 密码
    fetcher = Neo4jEntityFetcher(uri, user, password)
    knowledge_entities = fetcher.get_entities_by_label("knowledge")
    knowledge_entities.extend(fetcher.get_entities_by_label("entity"))

    texts = [str(i['properties']['name']) for i in knowledge_entities] 
    ids = [i['id'] for i in knowledge_entities]

    # source-cell:12
    model, tokenizer = LoadModel()
    def batch_encode_texts(model, tokenizer, texts, batch_size=32):
        embeddings = []
        for i in tqdm(range(0, len(texts), batch_size)):
            batch_texts = texts[i:i + batch_size]
            batch_embeddings = encode_text(model, tokenizer, batch_texts)
            embeddings.extend(batch_embeddings)
        return embeddings

    embeddings = batch_encode_texts(model, tokenizer, texts, batch_size=64)

    # source-cell:13
    embeddings = np.array(embeddings,dtype=np.float32)
    dim = embeddings.shape[1]
    index = faiss.IndexFlatL2(dim)  
    index.add(embeddings)

    faiss.write_index(index, '../../data/faiss_index/faiss_index.index')

    np.save('../../data/faiss_index/matedata.npy', ids)

    # source-cell:15
    import numpy as np
    import faiss
    from legacy.prototypes.rag.Embedding import (LoadModel, encode_text, warnings, os, pd, tqdm, KeyedVectors, AutoModel, AutoTokenizer, torch, nn)
    from Neo4jEntityFetcher import Neo4jEntityFetcher

    from langchain_core.output_parsers import JsonOutputParser,StrOutputParser
    from langchain_community.llms import Ollama
    from langchain_core.prompts import ChatPromptTemplate

    # source-cell:16
    loaded_index = faiss.read_index('../../data/faiss_index/faiss_index.index')
    loaded_ids = np.load('../../data/faiss_index/matedata.npy')

    # source-cell:17
    query_text = '肺结节'
    model, tokenizer = LoadModel()
    query_vector = encode_text(model, tokenizer, query_text)

    # source-cell:18
    # 进行查询
    D, I = loaded_index.search(np.array(query_vector, dtype=np.float32), k=3) 

    print("距离:", D)  # 距离
    print("索引:", I)  # 对应的索引
    print("ID:", [loaded_ids[i] for i in I[0]])

    # source-cell:19
    systemContent = """
        你是医学领域的专业大学教授，现在需要你根据我给你的数据描述出这段数据表达的知识点

        **输出要求:**
    
        - 我发给你的内容中包括我需要描述的知识点、以及与他有关的实体与实体的解释
        - 我给你的内容中的描述、类型、相关知识点、以及与他有关的实体可能有多种，你需要完整的描述
        - 你仅需要描述相关内容，不需要额外拓展
        - 尽量以严谨的科学口吻描述完整的描述
        - 返回内容为一段话即可，不需要复杂的格式
    """


    prompt_template = ChatPromptTemplate.from_messages(
        [("system", systemContent), ("user", "{text}")]
    )

    model = Ollama(model="qwen2.5",temperature=0.0)
    parser = StrOutputParser()
    chain =  prompt_template | model | parser

    # source-cell:20
    uri = "bolt://localhost:7687"  # Neo4j 数据库地址
    user = "neo4j"  # Neo4j 用户名
    password = "password"  # Neo4j 密码
    fetcher = Neo4jEntityFetcher(uri, user, password)

    knowledges = []
    for i in I[0]:
        entity_id = loaded_ids[i]
        entity = fetcher.get_entity_by_id(entity_id)
        knowledge = ''
        knowledge += entity[0]['properties']['name'] + '\n\n'
        if entity[0]['labels'][0] == 'entity':
            ent = fetcher.get_entities_by_entities_id(entity[0]['id'])  # 实体相关信息
            type = ''
            description = ''
            key = ent[0]['key']
            know = []
            relation = []
            for e in ent:
                if e['relationship']['type'] == 'type' and type == '':
                    type = e['properties']
                if e['relationship']['type'] == 'description' and description == '':
                    description = e['properties']
                if e['relationship']['type'] == 'knowledge':
                    know.append(e['properties'])
                if e['relationship']['type'] == 'relation':
                    relation.append((e['key'],e['relationship']['properties']['relation'],e['properties']))
            knowledge += f'{key,type,description},\n相关知识点：{know},\n相关实体：{relation}'
        if entity[0]['labels'][0] == 'knowledge':
            entities = fetcher.get_entities_by_knowledge_id(entity[0]['id'])  # 获取知识点相关实体
            types = []
            description = []
            for i in entities:
                ent = fetcher.get_entities_by_entities_id(i['id'])  # 实体相关信息
                type = ''
                description = ''
                key = ent[0]['key']
                for e in ent:
                    if e['relationship']['type'] == 'type' and type == '':
                        type = e['properties']
                    if e['relationship']['type'] == 'description' and description == '':
                        print(e)
                        description = e['properties']
                knowledge += f'{(key,description,type)}'
        print(knowledge,end='\n\n\n\n')
    
        response = chain.invoke({"text": knowledge})
        print(response,end='\n\n\n\n')
        knowledges.append(response)

    # source-cell:21
    # memory = ConversationBufferMemory(return_messages=True)

    knowledge = ''
    for i in I[0]:
        entity_id = loaded_ids[i]
        entity = fetcher.get_entity_by_id(entity_id)
        know = entity[0]['properties']['name']

        # memory.save_context({"input": know},{"output": "以上消息已加入知识库"})
        knowledge += f'{know}\n\n'

    # memory.load_memory_variables({})

    systemContent = """
        你是医学领域的专业大学教授，现在需要你根据我传递给你的知识点构建一道选择题

        **输出要求:**
    
        - 我发给你的内容是相关需要生成的试题的知识点
        - 你需要从我发给你的知识库中选择部分作为这道题目的主要考点
        - 你需要确保你给的题目具有逻辑性且有唯一正确答案
        - 你需要返回题目、选项、答案、解析
        - 题目的表达形式可以有多种、选项的内容的长度不做限制
        - 确保输出是紧凑格式的有效JSON格式，不包含任何其他解释、转义符、换行符或反斜杠
    
        **知识库内容:**
        {knowledge}

        **输出案例：**
    
        {{
          "topic": "往无任何神经系统症状，8小时前突发剧烈头痛，伴喷射状呕吐，肢体活动无障碍。应首选以下哪种检查",
          "options": {{
              "A": "头颅X线平片",
              "B": "穿颅多普勒",
              "C": "CT",
              "D": "MRI"
            }},
            "answer":"C",
            "parse":"血液溢出血管后形成血肿，大量的X线吸收系数明显高于脑实质的血红蛋白积聚在一起，CT图像上表现为高密度病灶，CT值多高于60Hu。"
        }}
    
    """


    prompt_template = ChatPromptTemplate.from_messages(
        [("system", systemContent), ("user", "{text}")]
    )

    model = Ollama(model="qwen2.5",temperature=0.3)
    parser = JsonOutputParser()
    chain =  prompt_template | model | parser

    for k in knowledges:
        response = chain.invoke({ "text": '','knowledge':k})
        print(response,end='\n\n')

    # source-cell:22


    # source-cell:23


    # source-cell:24



if __name__ == "__main__":
    print("Historical source archive. Use python -m backend.app.cli --help for supported commands.")
