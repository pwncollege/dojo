import random, json, string, sys
COUNT = 10000
if COUNT < 10: COUNT = 10
if COUNT > 15000: COUNT = 15000
seed = 12345
random.seed(seed)
modules_pool = [
"Your First Program","Software Introspection","Computer Memory","Hello Hackers",
"Assembly Crash Course","Debugging Refresher","Building a Web Server",
"Start Here","Linux Luminarium","Playing With Programs",
"Intro to Programming Languages","Reverse Engineering","Web Security",
"Computing 101","Pwntools Tutorials","The Art of the Shell",
"Fuzz Dojo","Privilege Escalation","Cryptographic Exploitation",
"Kernel Security","Windows Warzone","ARM Architecture","Content Injection",
"Adversarial Machine Learning Dojo","CTF Archive","Pwn.college Archives",
"Honors Dojo"
]

def rand_username():
    adj = ["dark","silent","red","ghost","x","zero","neo","crypt","byte","ninja","sudo","root","hex","sigma","omega"]
    noun = ["cat","snake","coder","hacker","phantom","cipher","viper","spectre","byte","reaver","spike","void","flux"]
    num = "".join(random.choices(string.digits, k=random.choice([0,2,3])))
    sep = random.choice(["", "_", ".", ""])
    base = random.choice(adj)+sep+random.choice(noun)+num
    if random.random() < 0.25:
        base = base.replace("a","@").replace("o","0").replace("e","3")
    if random.random() < 0.1:
        base = base + random.choice(["X","99","1337","_pwn"])
    return base
def make_user():
    mods = random.sample(modules_pool, k=random.randint(0, min(8,len(modules_pool))))
    per_mod_solves = [random.randint(1,10) for _ in mods]
    return {
        "Hacker UserName": rand_username(),
        "Number of Solves": sum(per_mod_solves),
        "Modules Solved": [{"module":m,"solves":s} for m,s in zip(mods,per_mod_solves)]
    }
users = [make_user() for _ in range(COUNT)]
with open("pwn_users.json","w") as f:
    json.dump(users,f,indent=2)
print("wrote",len(users),"users to pwn_users.json")
