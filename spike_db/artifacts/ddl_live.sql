\restrict hENW9y3gagQO1JkSgpqrnZK8P8g7HwJTZSUTJSCtTFO7EOiFDFibPnwBgL5xxC1
CREATE TABLE public.categories (
    slug text NOT NULL,
    label text NOT NULL,
    ages integer[] NOT NULL
);
CREATE TABLE public.category_membership (
    category_slug text NOT NULL,
    property_id integer NOT NULL,
    rank integer,
    low_usd numeric(12,2),
    high_usd numeric(12,2),
    feasible_months integer DEFAULT 0 NOT NULL,
    included boolean DEFAULT false NOT NULL
);
CREATE TABLE public.properties (
    id integer NOT NULL,
    lodge_slug text NOT NULL,
    property_slug text NOT NULL,
    name text NOT NULL,
    currency text,
    benchmark_year integer,
    benchmark_applicable boolean DEFAULT true NOT NULL,
    inclusion text,
    pricing_script_path text,
    dossier_path text
);
CREATE VIEW public.category_listing AS
 SELECT c.label AS category,
    cm.rank,
    p.name AS property,
    p.lodge_slug AS lodge,
    cm.low_usd AS adr_low_usd,
    cm.high_usd AS adr_high_usd,
    cm.feasible_months,
    cm.included,
    c.slug AS category_slug,
    p.property_slug
   FROM ((public.category_membership cm
     JOIN public.categories c ON ((c.slug = cm.category_slug)))
     JOIN public.properties p ON ((p.id = cm.property_id)))
  ORDER BY c.label, cm.included DESC, cm.rank, p.name;
CREATE TABLE public.evaluations (
    property_id integer NOT NULL,
    adr_json jsonb NOT NULL,
    fx_date date,
    evaluated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE SEQUENCE public.properties_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.properties_id_seq OWNED BY public.properties.id;
ALTER TABLE ONLY public.properties ALTER COLUMN id SET DEFAULT nextval('public.properties_id_seq'::regclass);
ALTER TABLE ONLY public.categories
    ADD CONSTRAINT categories_pkey PRIMARY KEY (slug);
ALTER TABLE ONLY public.category_membership
    ADD CONSTRAINT category_membership_pkey PRIMARY KEY (category_slug, property_id);
ALTER TABLE ONLY public.evaluations
    ADD CONSTRAINT evaluations_pkey PRIMARY KEY (property_id);
ALTER TABLE ONLY public.properties
    ADD CONSTRAINT properties_lodge_slug_property_slug_key UNIQUE (lodge_slug, property_slug);
ALTER TABLE ONLY public.properties
    ADD CONSTRAINT properties_pkey PRIMARY KEY (id);
CREATE INDEX idx_membership_category ON public.category_membership USING btree (category_slug, rank);
CREATE INDEX idx_membership_property ON public.category_membership USING btree (property_id);
ALTER TABLE ONLY public.category_membership
    ADD CONSTRAINT category_membership_category_slug_fkey FOREIGN KEY (category_slug) REFERENCES public.categories(slug) ON DELETE CASCADE;
ALTER TABLE ONLY public.category_membership
    ADD CONSTRAINT category_membership_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.evaluations
    ADD CONSTRAINT evaluations_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE CASCADE;
\unrestrict hENW9y3gagQO1JkSgpqrnZK8P8g7HwJTZSUTJSCtTFO7EOiFDFibPnwBgL5xxC1
