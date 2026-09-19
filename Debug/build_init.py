import sys
DD = chr(36) + chr(36)
SQ = chr(39)
out = sys.argv[1]

def w(f, t=""):
    f.write(t + chr(10))

with open(out, "w", encoding="utf-8") as f:
    w(f, "CREATE OR REPLACE FUNCTION update_updated_at_column()")
    w(f, "RETURNS TRIGGER AS " + DD)
    w(f, "BEGIN")
    w(f, "    NEW.updated_at = NOW();")
    w(f, "    RETURN NEW;")
    w(f, "END;")
    w(f, DD + " LANGUAGE plpgsql;")
    w(f)

print("P1 done")
